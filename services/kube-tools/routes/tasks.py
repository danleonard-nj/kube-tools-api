import base64
import traceback

from pydantic import BaseModel
from quart import request

from domain.auth import AuthPolicy
from framework.logger import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from models.task_models import GeneratedTask, GoogleTaskPayload, TaskListSummary
from services.task_service import TaskService

logger = get_logger(__name__)

tasks_bp = MetaBlueprint('tasks_bp', __name__)


class TaskPromptRequest(BaseModel):
    prompt: str | None = None
    image_base64: str | None = None
    text: str | None = None


@tasks_bp.configure('/api/tasks/lists', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_task_lists(container):
    service: TaskService = container.resolve(TaskService)

    task_lists = await service.get_task_lists()
    summaries = [
        TaskListSummary(id=tl['id'], title=tl['title'])
        for tl in task_lists
    ]

    return [s.model_dump(mode='json') for s in summaries]


@tasks_bp.configure('/api/tasks', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_tasks(container):
    service: TaskService = container.resolve(TaskService)

    task_list = request.args.get('task_list')
    tasks = await service.list_tasks(task_list=task_list)

    return tasks


@tasks_bp.configure('/api/tasks/prompt', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_task_prompt(container):
    """Generate a task preview from a prompt, an image, or both. Does not save anything."""
    service: TaskService = container.resolve(TaskService)

    data = await request.get_json()
    model = TaskPromptRequest.model_validate(data)

    image_bytes = base64.b64decode(model.image_base64) if model.image_base64 else None

    task = await service.create_task_from_input(
        prompt=model.prompt,
        image_bytes=image_bytes,
        text=model.text)

    return task.model_dump(mode='json')


@tasks_bp.configure('/api/tasks/save', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_task_save(container):
    service: TaskService = container.resolve(TaskService)

    data = await request.get_json()
    model = GeneratedTask.model_validate(data)

    result = await service.save_generated_task(model)

    return result.model_dump(mode='json')


@tasks_bp.configure('/api/tasks/<task_id>', methods=['PATCH'], auth_scheme=AuthPolicy.Default)
async def patch_task(container, task_id):
    service: TaskService = container.resolve(TaskService)

    data = await request.get_json()
    task_list_id = await service.resolve_task_list_id(data.pop('task_list', None))
    payload = GoogleTaskPayload.model_validate(data)

    result = await service.update_task(task_list_id, task_id, payload)

    return result


@tasks_bp.configure('/api/tasks/<task_id>/complete', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_task_complete(container, task_id):
    service: TaskService = container.resolve(TaskService)

    data = await request.get_json(silent=True) or {}
    task_list_id = await service.resolve_task_list_id(data.get('task_list'))

    result = await service.complete_task(task_list_id, task_id)

    return result


@tasks_bp.configure('/api/tasks/<task_id>', methods=['DELETE'], auth_scheme=AuthPolicy.Default)
async def delete_task(container, task_id):
    service: TaskService = container.resolve(TaskService)

    data = await request.get_json(silent=True) or {}
    task_list_id = await service.resolve_task_list_id(data.get('task_list'))

    await service.delete_task(task_list_id, task_id)

    return {'deleted': True}


@tasks_bp.configure('/api/tasks/poll', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_task_poll(container):
    """External scheduled-caller entrypoint that materializes due recurring occurrences."""
    service: TaskService = container.resolve(TaskService)

    body = await request.get_json(silent=True) or {}

    try:
        result = await service.poll_due_tasks(
            definition_limit=body.get('definition_limit', 100),
            catch_up_limit=body.get('catch_up_limit', 25))
    except Exception:
        logger.error(f'Task poll failed: {traceback.format_exc()}')
        return {'error': 'Task poll failed'}, 500

    return result.model_dump()


@tasks_bp.configure(
    '/api/tasks/internal/summary',
    methods=['GET'],
    auth_scheme=AuthPolicy.Default,
)
async def get_task_summary(container):
    """Internal endpoint: live Google Tasks summary, sorted by due date."""
    service: TaskService = container.resolve(TaskService)

    summary = await service.get_task_summary()

    return summary.model_dump(mode='json')


@tasks_bp.configure(
    '/api/tasks/internal/summary/email',
    methods=['POST'],
    auth_scheme=AuthPolicy.Default,
)
async def post_task_summary_email(container):
    """Internal endpoint: send the task summary email via the configured Brevo recipient."""
    service: TaskService = container.resolve(TaskService)

    summary = await service.send_task_summary_email()

    return {
        'sent': True,
        'task_count': len(summary.tasks),
    }
