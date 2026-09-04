import asyncio
import base64
import html
import traceback
from datetime import date, datetime, timedelta, timezone
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from clients.gpt_client import GPTClient, GptResponseToolType
from clients.sib_client import SendInBlueClient
from data.google.google_tasks_repository import TaskRepository
from domain.gpt import GPTModel
from domain.tasks import (
    SAMPLE_GENERATED_TASK_JSON,
    InvalidTaskRecurrenceException,
    NoTaskInputProvidedException,
    TaskDependencyValidationException,
    TaskListNotFoundException,
    TaskSaveCompensationException,
    build_start_datetime,
    calculate_next_occurrence,
    format_google_due_date,
    parse_google_due_date,
    parse_recurrence,
)
from framework.clients.feature_client import FeatureClientAsync
from framework.logger import get_logger
from googleapiclient.discovery import build
from models.task_models import (
    GeneratedTask,
    GoogleTaskPayload,
    SavedTaskResult,
    TaskConfig,
    TaskDefinition,
    TaskDependency,
    TaskOccurrence,
    TaskPollResult,
    TaskSummary,
    TaskSummaryItem,
)
from services.google_auth_service import GoogleAuthService
from utilities.utils import strip_json_backticks

logger = get_logger(__name__)

DEFAULT_TASK_TIME = dt_time(9, 0)
DEFAULT_TASK_LIST_NAME = 'Default'
DEFAULT_GOOGLE_TASK_LIST_ID = '@default'
GPT_MODEL_FEATURE_KEY = 'gpt-model-task-service'

GOOGLE_READ_RETRIES = 3
GOOGLE_WRITE_RETRIES = 1

MAX_DEFINITION_LIMIT = 200
MAX_CATCH_UP_LIMIT = 50


def _get_system_prompt() -> str:
    return f'''You are a helpful assistant that generates a single JSON Google Task based on user input.
Your task is to create a JSON object that represents one Google Task.
If a location or detail is vague or incomplete, use web_search to resolve specifics.

The JSON object must look exactly like this:
{SAMPLE_GENERATED_TASK_JSON}

Rules:
- Generate exactly one task.
- The title must be concise and actionable.
- Put supporting details, instructions, addresses, phone numbers, links, or web findings in notes.
- Resolve relative dates using the supplied current local date and time.
- Only set recurrence when the user explicitly requested a repeating task; never invent recurrence.
- recurrence must contain RFC 5545 lines (one RRULE, optionally RDATE/EXDATE lines).
- due_date/due_time must hold the first concrete occurrence.
- Use null for unknown scalar values and an empty list for no recurrence.
- Never generate Google or MongoDB IDs.
- Never generate task dependencies.

Respond ONLY with a JSON object. DO NOT include markdown formatting, commentary, headings, or explanations.
The first character must be '{{' and the last character must be '}}'.'''


def _get_user_prompt(
    locality: str,
    time_zone: str,
    text: str | None,
    has_image: bool,
    available_task_categories: list[str],
) -> str:
    task_text = f'Task: {text}\n' if text else ''
    image_instruction = (
        '\nIf an image is provided, extract all relevant task details from it.'
        if has_image
        else ''
    )
    now_local = datetime.now(ZoneInfo(time_zone))
    categories_text = '\n'.join(
        f'- {category}'
        for category in available_task_categories
    )

    return f'''Create a Google Task from the following details:

{task_text}User locality: {locality}
User time zone: {time_zone}
Current local date and time: {now_local.strftime('%Y-%m-%d %H:%M:%S')}

Instructions:
- Use a concise, actionable title
- Put supporting details in notes
- Use RFC 5545 recurrence lines only if recurrence was explicitly requested
- task_list must be one exact value from the available task categories

Available task categories:
{categories_text}

Choose exactly one category from this list.
Use "Default" when none clearly fits.
Do not invent, rename, or return any category not listed.
- Output ONLY the JSON object{image_instruction}'''


def _build_image_data_url(image_bytes: bytes) -> str:
    mimetype = (
        'image/png'
        if image_bytes.startswith(b'\x89PNG')
        else 'image/jpeg'
    )
    encoded = base64.b64encode(image_bytes).decode('utf-8')
    return f'data:{mimetype};base64,{encoded}'


def _format_summary_due_date(due_date: date | None) -> str:
    if due_date is None:
        return '-'
    return due_date.strftime('%b %d, %Y')


def _build_task_summary_email_html(
    summary: TaskSummary,
    current_local_date: date | None = None,
) -> str:
    if not summary.tasks:
        return 'No incomplete tasks.'

    current_local_date = current_local_date or date.today()

    rows = []

    for item in summary.tasks:
        is_overdue = (
            item.due_date is not None
            and item.due_date < current_local_date
        )
        row_style = (
            ' style="background-color: #fdecec;"'
            if is_overdue
            else ''
        )
        due_cell_style = (
            ' style="font-weight: 600;"'
            if is_overdue
            else ''
        )

        rows.append(
            '    <tr'
            f'{row_style}>'
            f'<td>{html.escape(item.title)}</td>'
            f'<td>{html.escape(item.task_list)}</td>'
            f'<td{due_cell_style}>'
            f'{_format_summary_due_date(item.due_date)}</td>'
            '</tr>'
        )

    return f'''<table cellpadding="6" style="border-collapse: collapse;">
  <thead>
    <tr>
      <th align="left">Task</th>
      <th align="left">Category</th>
      <th align="left">Due</th>
    </tr>
  </thead>
  <tbody>
{chr(10).join(rows)}
  </tbody>
</table>'''

# TODO: Create new task category (list) feature
class TaskService:
    def __init__(
        self,
        auth_service: GoogleAuthService,
        repository: TaskRepository,
        gpt_client: GPTClient,
        config: TaskConfig,
        feature_client: FeatureClientAsync,
        sib_client: SendInBlueClient,
    ):
        self._auth_service = auth_service
        self._repository = repository
        self._gpt_client = gpt_client
        self._config = config
        self._feature_client = feature_client
        self._sib_client = sib_client
        self._indexes_ensured = False

    async def _ensure_indexes(self) -> None:
        if self._indexes_ensured:
            return

        await self._repository.ensure_indexes()
        self._indexes_ensured = True

    async def _get_task_gpt_model(self) -> str:
        configured_model = await self._feature_client.is_enabled(
            GPT_MODEL_FEATURE_KEY
        )
        return configured_model or GPTModel.GPT_4_1_MINI

    def _default_task_time(self) -> dt_time:
        raw = self._config.preferences.get('default_task_time')
        if not raw:
            return DEFAULT_TASK_TIME

        return datetime.strptime(raw, '%H:%M').time()

    def _build_available_task_categories(
        self,
        task_lists: list[dict],
    ) -> list[str]:
        categories: list[str] = [DEFAULT_TASK_LIST_NAME]
        seen = {DEFAULT_TASK_LIST_NAME.casefold()}

        for task_list in task_lists:
            title = (task_list.get('title') or '').strip()
            if not title:
                continue

            title_key = title.casefold()
            if title_key in seen:
                continue

            seen.add(title_key)
            categories.append(title)

        return categories

    def _normalize_generated_task_list(
        self,
        generated_task_list: str | None,
        available_task_categories: list[str],
    ) -> str:
        if not generated_task_list:
            return DEFAULT_TASK_LIST_NAME

        normalized_key = generated_task_list.strip().casefold()
        for category in available_task_categories:
            if category.casefold() == normalized_key:
                return category

        return DEFAULT_TASK_LIST_NAME

    # ------------------------------------------------------------------
    # Google Tasks client
    # ------------------------------------------------------------------

    async def get_task_client(self):
        """
        Build a new Google Tasks service for each operation.

        googleapiclient uses httplib2 underneath. Its transport should not be
        cached and shared across concurrent asyncio.to_thread executions.
        """
        logger.info('Fetching Google Tasks client')

        credentials = await self._auth_service.get_credentials(
            client_name='tasks-client',
            scopes=['https://www.googleapis.com/auth/tasks'],
        )

        return build(
            'tasks',
            'v1',
            credentials=credentials,
            cache_discovery=False,
        )

    async def _execute_read(self, request):
        """
        Execute an idempotent Google API request outside the Quart event loop.

        Read operations receive additional transport retries because transient
        TLS and connection failures can be retried safely.
        """
        return await asyncio.to_thread(
            request.execute,
            num_retries=GOOGLE_READ_RETRIES,
        )

    async def _execute_write(self, request):
        """
        Execute a Google API mutation outside the Quart event loop.

        Keep write retries lower because a transport failure can occur after
        Google accepted a mutation but before the response reached this client.
        """
        return await asyncio.to_thread(
            request.execute,
            num_retries=GOOGLE_WRITE_RETRIES,
        )

    # ------------------------------------------------------------------
    # Google Tasks operations
    # ------------------------------------------------------------------

    async def get_task_lists(self) -> list[dict]:
        service = await self.get_task_client()

        task_lists: list[dict] = []
        page_token = None

        while True:
            response = await self._execute_read(
                service.tasklists().list(
                    pageToken=page_token,
                )
            )

            task_lists.extend(response.get('items', []))
            page_token = response.get('nextPageToken')

            if not page_token:
                break

        return task_lists

    # async def resolve_task_list_id(
    #     self,
    #     task_list_name: str | None,
    # ) -> str:
    #     requested_name = (
    #         task_list_name
    #         or self._config.preferences.get('default_task_list')
    #     )

    #     if not requested_name:
    #         return DEFAULT_GOOGLE_TASK_LIST_ID

    #     task_lists = await self.get_task_lists()

    #     for task_list in task_lists:
    #         title = task_list.get('title', '')
    #         if title.casefold() == requested_name.casefold():
    #             return task_list['id']

    #     raise TaskListNotFoundException(requested_name)

    # Fixing default task handling
    async def resolve_task_list_id(
        self,
        task_list_name: str | None,
    ) -> str:
        if (
            not task_list_name
            or task_list_name.casefold() == DEFAULT_TASK_LIST_NAME.casefold()
            or task_list_name == DEFAULT_GOOGLE_TASK_LIST_ID
        ):
            return DEFAULT_GOOGLE_TASK_LIST_ID

        task_lists = await self.get_task_lists()

        for task_list in task_lists:
            title = task_list.get('title', '')

            if title.casefold() == task_list_name.casefold():
                return task_list['id']

        raise TaskListNotFoundException(task_list_name)

    async def get_tasks(
        self,
        task_list_id: str,
        show_completed: bool = False,
    ) -> list[dict]:
        service = await self.get_task_client()

        tasks: list[dict] = []
        page_token = None

        while True:
            response = await self._execute_read(
                service.tasks().list(
                    tasklist=task_list_id,
                    showCompleted=show_completed,
                    pageToken=page_token,
                )
            )

            tasks.extend(response.get('items', []))
            page_token = response.get('nextPageToken')

            if not page_token:
                break

        return tasks

    async def list_tasks(
        self,
        task_list: str | None = None,
        show_completed: bool = False,
    ) -> list[dict]:
        task_list_id = await self.resolve_task_list_id(task_list)

        return await self.get_tasks(
            task_list_id,
            show_completed=show_completed,
        )

    async def get_task(
        self,
        task_list_id: str,
        task_id: str,
    ) -> dict:
        service = await self.get_task_client()

        return await self._execute_read(
            service.tasks().get(
                tasklist=task_list_id,
                task=task_id,
            )
        )

    async def create_task(
        self,
        task_list_id: str,
        task: GoogleTaskPayload,
    ) -> dict:
        service = await self.get_task_client()

        created = await self._execute_write(
            service.tasks().insert(
                tasklist=task_list_id,
                body=task.model_dump(exclude_none=True),
            )
        )

        logger.info(
            f"Created Google task '{created.get('id')}' "
            f"in list '{task_list_id}'"
        )

        return created

    async def update_task(
        self,
        task_list_id: str,
        task_id: str,
        task: GoogleTaskPayload,
    ) -> dict:
        service = await self.get_task_client()

        return await self._execute_write(
            service.tasks().patch(
                tasklist=task_list_id,
                task=task_id,
                body=task.model_dump(exclude_none=True),
            )
        )

    async def complete_task(
        self,
        task_list_id: str,
        task_id: str,
    ) -> dict:
        service = await self.get_task_client()

        return await self._execute_write(
            service.tasks().patch(
                tasklist=task_list_id,
                task=task_id,
                body={'status': 'completed'},
            )
        )

    async def delete_task(
        self,
        task_list_id: str,
        task_id: str,
    ) -> None:
        service = await self.get_task_client()

        await self._execute_write(
            service.tasks().delete(
                tasklist=task_list_id,
                task=task_id,
            )
        )

    # ------------------------------------------------------------------
    # LLM task generation
    # ------------------------------------------------------------------

    async def create_task_from_input(
        self,
        prompt: str | None = None,
        image_bytes: bytes | None = None,
        text: str | None = None,
    ) -> GeneratedTask:
        if not prompt and not image_bytes and not text:
            raise NoTaskInputProvidedException()

        locality = self._config.preferences.get(
            'home',
            'New Jersey',
        )
        time_zone = self._config.preferences.get(
            'time_zone',
            'America/New_York',
        )
        model = await self._get_task_gpt_model()
        task_lists = await self.get_task_lists()
        available_task_categories = self._build_available_task_categories(
            task_lists
        )

        system_prompt = _get_system_prompt()
        user_prompt = _get_user_prompt(
            locality=locality,
            time_zone=time_zone,
            text=text or prompt,
            has_image=bool(image_bytes),
            available_task_categories=available_task_categories,
        )

        logger.info(f'Generating task with model: {model}')

        if image_bytes:
            result = (
                await self._gpt_client.generate_response_with_image_and_tools(
                    image_bytes=_build_image_data_url(image_bytes),
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    model=model,
                    custom_tools=[
                        {
                            'type':
                                GptResponseToolType.WEB_SEARCH_PREVIEW
                        }
                    ],
                )
            )
        else:
            result = await self._gpt_client.generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=model,
                custom_tools=[
                    {
                        'type':
                            GptResponseToolType.WEB_SEARCH_PREVIEW
                    }
                ],
            )

        logger.info(
            f'Used {result.usage} tokens with model {model}'
        )

        response_text = strip_json_backticks(result.text)

        generated_task = GeneratedTask.model_validate_json(
            response_text,
            strict=True,
        )

        generated_task.task_list = self._normalize_generated_task_list(
            generated_task.task_list,
            available_task_categories,
        )

        return generated_task

    # ------------------------------------------------------------------
    # Saving tasks
    # ------------------------------------------------------------------

    async def save_generated_task(
        self,
        task: GeneratedTask,
    ) -> SavedTaskResult:
        await self._ensure_indexes()

        logger.info(f'Saving task: {task.title}')

        task_list_id = await self.resolve_task_list_id(
            task.task_list
        )

        starts_at = None

        if task.recurrence:
            starts_at = build_start_datetime(
                task,
                self._default_task_time(),
            )

            # Validate recurrence before any Google or MongoDB write.
            parse_recurrence(
                task.recurrence,
                starts_at,
            )

        payload = GoogleTaskPayload(
            title=task.title,
            notes=task.notes,
            due=format_google_due_date(task.due_date),
        )

        created = await self.create_task(
            task_list_id,
            payload,
        )

        if not task.recurrence:
            return SavedTaskResult(
                task=created,
                task_definition_id=None,
            )

        try:
            definition = await self._persist_recurrence(
                task=task,
                task_list_id=task_list_id,
                starts_at=starts_at,
                google_task_id=created['id'],
            )
        except Exception as error:
            logger.error(
                f"Failed to persist recurrence for Google task "
                f"'{created.get('id')}': {error}"
            )

            await self._compensate_google_task(
                task_list_id,
                created.get('id'),
            )

            raise TaskSaveCompensationException(
                f"Google task '{created.get('id')}' was created "
                f'but recurrence persistence failed'
            ) from error

        return SavedTaskResult(
            task=created,
            task_definition_id=definition.id,
        )

    async def _persist_recurrence(
        self,
        task: GeneratedTask,
        task_list_id: str,
        starts_at: datetime,
        google_task_id: str,
    ) -> TaskDefinition:
        starts_at_utc = starts_at.astimezone(timezone.utc)

        next_occurrence = calculate_next_occurrence(
            task.recurrence,
            starts_at,
            starts_at,
        )

        next_occurrence_utc = (
            next_occurrence.astimezone(timezone.utc)
            if next_occurrence
            else None
        )

        now = datetime.now(timezone.utc)

        definition = await self._repository.create_definition(
            TaskDefinition(
                google_task_list_id=task_list_id,
                title=task.title,
                notes=task.notes,
                starts_at=starts_at_utc,
                recurrence=task.recurrence,
                next_occurrence_at=next_occurrence_utc,
                last_materialized_at=None,
                active=True,
                created_at=now,
                updated_at=now,
            )
        )

        logger.info(
            f"Created task definition '{definition.id}'"
        )

        occurrence, _ = (
            await self._repository.create_occurrence_if_missing(
                TaskOccurrence(
                    task_definition_id=definition.id,
                    scheduled_for=starts_at_utc,
                    created_at=now,
                )
            )
        )

        await self._repository.set_occurrence_google_task_id(
            occurrence.id,
            google_task_id,
        )

        definition.last_materialized_at = now
        definition.updated_at = now

        return await self._repository.update_definition(
            definition
        )

    async def _compensate_google_task(
        self,
        task_list_id: str,
        task_id: str | None,
    ) -> None:
        if not task_id:
            return

        try:
            await self.delete_task(
                task_list_id,
                task_id,
            )

            logger.info(
                f"Compensated by deleting Google task '{task_id}' "
                f'after persistence failure'
            )
        except Exception as compensation_error:
            logger.error(
                f"Failed to compensate Google task '{task_id}': "
                f'{compensation_error}'
            )

    # ------------------------------------------------------------------
    # Task dependencies
    # ------------------------------------------------------------------

    async def create_task_dependency(
        self,
        predecessor_task_definition_id: str,
        successor_task_definition_id: str,
        delay_seconds: int = 0,
    ) -> TaskDependency:
        predecessor = await self._repository.get_definition(
            predecessor_task_definition_id
        )

        if not predecessor:
            raise TaskDependencyValidationException(
                f"Predecessor task definition "
                f"'{predecessor_task_definition_id}' does not exist"
            )

        successor = await self._repository.get_definition(
            successor_task_definition_id
        )

        if not successor:
            raise TaskDependencyValidationException(
                f"Successor task definition "
                f"'{successor_task_definition_id}' does not exist"
            )

        dependency = TaskDependency(
            predecessor_task_definition_id=(
                predecessor_task_definition_id
            ),
            successor_task_definition_id=(
                successor_task_definition_id
            ),
            delay_seconds=delay_seconds,
            created_at=datetime.now(timezone.utc),
        )

        return await self._repository.create_dependency(
            dependency
        )

    # ------------------------------------------------------------------
    # Task summary
    # ------------------------------------------------------------------

    async def get_task_summary(self) -> TaskSummary:
        """Build a summary of incomplete tasks, live from Google Tasks."""
        task_lists = await self.get_task_lists()

        items: list[TaskSummaryItem] = []

        for task_list in task_lists:
            task_list_id = task_list.get('id')
            task_list_title = task_list.get('title', '')

            tasks = await self.get_tasks(
                task_list_id,
                show_completed=False,
            )

            for task in tasks:
                items.append(TaskSummaryItem(
                    id=task['id'],
                    title=task.get('title', ''),
                    task_list=task_list_title,
                    due_date=parse_google_due_date(task.get('due')),
                    notes=task.get('notes'),
                ))

        # Dated tasks first (ascending), undated tasks last; title breaks ties.
        items.sort(
            key=lambda item: (
                item.due_date is None,
                item.due_date or date.max,
                item.title,
            )
        )

        return TaskSummary(
            generated_at=datetime.now(timezone.utc),
            tasks=items,
        )

    async def send_task_summary_email(self) -> TaskSummary:
        summary = await self.get_task_summary()

        recipient = self._config.preferences.get('email')
        time_zone = self._config.preferences.get(
            'time_zone',
            'America/New_York',
        )
        current_local_date = datetime.now(ZoneInfo(time_zone)).date()
        html_body = _build_task_summary_email_html(
            summary,
            current_local_date=current_local_date,
        )

        await self._sib_client.send_email(
            recipient=recipient,
            subject='Task Summary',
            html_body=html_body,
        )

        return summary

    # ------------------------------------------------------------------
    # Polling recurrence
    # ------------------------------------------------------------------

    async def poll_due_tasks(
        self,
        through: datetime | None = None,
        definition_limit: int = 100,
        catch_up_limit: int = 25,
    ) -> TaskPollResult:
        await self._ensure_indexes()

        through = through or (
            datetime.now(timezone.utc)
            + timedelta(minutes=5)
        )

        definition_limit = min(
            definition_limit,
            MAX_DEFINITION_LIMIT,
        )
        catch_up_limit = min(
            catch_up_limit,
            MAX_CATCH_UP_LIMIT,
        )

        logger.info(
            f'Polling due tasks through {through.isoformat()} '
            f'(definition_limit={definition_limit}, '
            f'catch_up_limit={catch_up_limit})'
        )

        result = TaskPollResult()

        definitions = (
            await self._repository.get_due_definitions(
                through,
                definition_limit,
            )
        )

        for definition in definitions:
            try:
                await self._poll_definition(
                    definition=definition,
                    through=through,
                    catch_up_limit=catch_up_limit,
                    result=result,
                )

                result.definitions_processed += 1
            except Exception:
                logger.error(
                    f"Failed to poll task definition "
                    f"'{definition.id}': "
                    f'{traceback.format_exc()}'
                )

                result.failures += 1

        logger.info(
            f'Poll summary: '
            f'processed={result.definitions_processed} '
            f'created={result.occurrences_created} '
            f'skipped={result.occurrences_skipped} '
            f'exhausted={result.definitions_exhausted} '
            f'failures={result.failures}'
        )

        return result

    async def _poll_definition(
        self,
        definition: TaskDefinition,
        through: datetime,
        catch_up_limit: int,
        result: TaskPollResult,
    ) -> None:
        processed_count = 0
        next_occurrence_at = definition.next_occurrence_at

        while (
            next_occurrence_at is not None
            and next_occurrence_at <= through
            and processed_count < catch_up_limit
        ):
            occurrence, was_created = (
                await self._repository.create_occurrence_if_missing(
                    TaskOccurrence(
                        task_definition_id=definition.id,
                        scheduled_for=next_occurrence_at,
                        created_at=datetime.now(timezone.utc),
                    )
                )
            )

            if was_created:
                payload = GoogleTaskPayload(
                    title=definition.title,
                    notes=definition.notes,
                    due=format_google_due_date(
                        next_occurrence_at.date()
                    ),
                )

                try:
                    created = await self.create_task(
                        definition.google_task_list_id,
                        payload,
                    )
                except Exception:
                    # Remove the unmaterialized claim so a later poll can retry.
                    await self._repository.delete_occurrence(
                        occurrence.id
                    )
                    raise

                await self._repository.set_occurrence_google_task_id(
                    occurrence.id,
                    created['id'],
                )

                result.occurrences_created += 1

                logger.info(
                    f"Materialized occurrence '{occurrence.id}' "
                    f"for definition '{definition.id}' at "
                    f'{next_occurrence_at.isoformat()}'
                )
            else:
                result.occurrences_skipped += 1

            definition.last_materialized_at = datetime.now(
                timezone.utc
            )

            next_occurrence_at = calculate_next_occurrence(
                definition.recurrence,
                definition.starts_at,
                next_occurrence_at,
            )

            processed_count += 1

        if (
            next_occurrence_at is not None
            and next_occurrence_at <= through
            and processed_count >= catch_up_limit
        ):
            logger.warning(
                f"Catch-up limit reached for task definition "
                f"'{definition.id}'; further occurrences will be "
                f'processed on the next poll'
            )

        definition.next_occurrence_at = next_occurrence_at

        if next_occurrence_at is None:
            definition.active = False
            result.definitions_exhausted += 1

        definition.updated_at = datetime.now(timezone.utc)

        await self._repository.update_definition(
            definition
        )