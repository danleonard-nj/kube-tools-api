"""Unit tests for TaskService and the recurrence/domain helpers."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from domain.tasks import (InvalidTaskRecurrenceException,
                          NoTaskInputProvidedException,
                          TaskDependencyValidationException,
                          TaskListNotFoundException, calculate_next_occurrence,
                          parse_google_due_date, parse_recurrence)
from models.task_models import (GeneratedTask, TaskConfig, TaskDefinition,
                                TaskDependency, TaskOccurrence, TaskSummary,
                                TaskSummaryItem)
from services.task_service import (TaskService,
                                   _build_task_summary_email_html)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task_service(repository=None, gpt_client=None, auth_service=None, feature_client=None, config=None, sib_client=None):
    repository = repository or AsyncMock()
    gpt_client = gpt_client or AsyncMock()
    auth_service = auth_service or AsyncMock()
    feature_client = feature_client or AsyncMock()
    feature_client.is_enabled = AsyncMock(return_value=None)
    sib_client = sib_client or AsyncMock()
    config = config or TaskConfig(
        preferences={'home': 'Southern New Jersey', 'time_zone': 'America/New_York'})

    return TaskService(
        auth_service=auth_service,
        repository=repository,
        gpt_client=gpt_client,
        config=config,
        feature_client=feature_client,
        sib_client=sib_client,
    )


def _generated_task_json(**overrides) -> str:
    data = {
        'title': 'Buy milk',
        'notes': None,
        'task_list': None,
        'due_date': None,
        'due_time': None,
        'time_zone': 'America/New_York',
        'recurrence': [],
    }
    data.update(overrides)
    return json.dumps(data)


# ---------------------------------------------------------------------------
# Pure recurrence/domain helper tests
# ---------------------------------------------------------------------------

def test_calculate_next_occurrence_weekly():
    starts_at = datetime(2026, 8, 6, 20, 0)  # Thursday

    next_occurrence = calculate_next_occurrence(
        ['RRULE:FREQ=WEEKLY;BYDAY=TH'], starts_at, starts_at)

    assert next_occurrence == datetime(2026, 8, 13, 20, 0)


def test_recurrence_with_rdate_and_exdate():
    starts_at = datetime(2026, 8, 6, 20, 0)
    recurrence = [
        'RRULE:FREQ=WEEKLY;BYDAY=TH;COUNT=2',
        'RDATE:20260827T200000',
        'EXDATE:20260813T200000',
    ]

    rule_set = parse_recurrence(recurrence, starts_at)
    occurrences = list(rule_set)

    assert datetime(2026, 8, 6, 20, 0) in occurrences
    assert datetime(2026, 8, 13, 20, 0) not in occurrences
    assert datetime(2026, 8, 27, 20, 0) in occurrences


def test_invalid_recurrence_raises_before_writes():
    starts_at = datetime(2026, 8, 6, 20, 0)

    with pytest.raises(InvalidTaskRecurrenceException):
        parse_recurrence(['NOT_A_VALID_RRULE_LINE'], starts_at)


def test_generated_task_recurrence_without_due_date_rejected():
    with pytest.raises(ValidationError):
        GeneratedTask(title='Trash day', recurrence=['RRULE:FREQ=WEEKLY;BYDAY=TH'])


def test_task_occurrence_triggered_by_occurrence_id_persists():
    occurrence = TaskOccurrence(
        task_definition_id='def-1',
        scheduled_for=datetime.now(timezone.utc),
        triggered_by_occurrence_id='occ-parent')

    assert occurrence.triggered_by_occurrence_id == 'occ-parent'


def test_task_dependency_rejects_self_dependency():
    with pytest.raises(ValidationError):
        TaskDependency(
            predecessor_task_definition_id='def-1',
            successor_task_definition_id='def-1')


def test_task_dependency_rejects_negative_delay():
    with pytest.raises(ValidationError):
        TaskDependency(
            predecessor_task_definition_id='def-1',
            successor_task_definition_id='def-2',
            delay_seconds=-5)


def test_parse_google_due_date_parses_rfc3339():
    assert parse_google_due_date('2026-08-06T00:00:00.000Z') == date(2026, 8, 6)


def test_parse_google_due_date_none_for_missing():
    assert parse_google_due_date(None) is None


# ---------------------------------------------------------------------------
# TaskService.create_task_from_input
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_from_input_returns_generated_task():
    gpt_client = AsyncMock()
    gpt_client.generate_response = AsyncMock(
        return_value=MagicMock(
            text=_generated_task_json(task_list='personal'),
            usage=42,
        ))

    service = make_task_service(gpt_client=gpt_client)
    service.get_task_lists = AsyncMock(return_value=[
        {'id': 'list-1', 'title': 'Personal'},
        {'id': 'list-2', 'title': 'Work'},
    ])

    task = await service.create_task_from_input(prompt='remind me to buy milk')

    assert isinstance(task, GeneratedTask)
    assert task.title == 'Buy milk'
    assert task.task_list == 'Personal'
    assert task.recurrence == []

    gpt_client.generate_response.assert_awaited_once()
    user_prompt = gpt_client.generate_response.await_args.kwargs['prompt']
    assert 'Available task categories:' in user_prompt
    assert '- Default' in user_prompt
    assert '- Personal' in user_prompt
    assert '- Work' in user_prompt


@pytest.mark.asyncio
async def test_create_task_from_input_invalid_task_list_falls_back_to_default():
    gpt_client = AsyncMock()
    gpt_client.generate_response = AsyncMock(
        return_value=MagicMock(
            text=_generated_task_json(task_list='Invented List'),
            usage=42,
        ))

    service = make_task_service(gpt_client=gpt_client)
    service.get_task_lists = AsyncMock(return_value=[
        {'id': 'list-1', 'title': 'Personal'},
    ])

    task = await service.create_task_from_input(prompt='remind me to buy milk')

    assert task.task_list == 'Default'


@pytest.mark.asyncio
async def test_create_task_from_input_requires_input():
    service = make_task_service()

    with pytest.raises(NoTaskInputProvidedException):
        await service.create_task_from_input()


# ---------------------------------------------------------------------------
# TaskService.resolve_task_list_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_task_list_id_case_insensitive():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[
        {'id': 'list-1', 'title': 'Personal'},
        {'id': 'list-2', 'title': 'Work'},
    ])

    list_id = await service.resolve_task_list_id('personal')

    assert list_id == 'list-1'


@pytest.mark.asyncio
async def test_resolve_task_list_id_missing_raises():
    service = make_task_service()
    service.get_task_lists = AsyncMock(
        return_value=[{'id': 'list-1', 'title': 'Personal'}])

    with pytest.raises(TaskListNotFoundException):
        await service.resolve_task_list_id('Nonexistent')


@pytest.mark.asyncio
async def test_resolve_task_list_id_default_fallback():
    service = make_task_service()
    service.get_task_lists = AsyncMock()

    list_id = await service.resolve_task_list_id(None)

    assert list_id == '@default'
    service.get_task_lists.assert_not_called()


# ---------------------------------------------------------------------------
# Google Tasks pagination / blocking execute
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_tasks_pagination_follows_next_page_token():
    service = make_task_service()
    service.get_task_client = AsyncMock(return_value=MagicMock())

    page_1 = {'items': [{'id': 't1'}], 'nextPageToken': 'page-2'}
    page_2 = {'items': [{'id': 't2'}]}
    service._execute = AsyncMock(side_effect=[page_1, page_2])

    tasks = await service.get_tasks('list-1')

    assert [t['id'] for t in tasks] == ['t1', 't2']
    assert service._execute.await_count == 2


@pytest.mark.asyncio
async def test_execute_uses_asyncio_to_thread(monkeypatch):
    service = make_task_service()
    request = MagicMock()
    request.execute = MagicMock(return_value={'ok': True})

    to_thread_mock = AsyncMock(return_value={'ok': True})
    monkeypatch.setattr(asyncio, 'to_thread', to_thread_mock)

    result = await service._execute(request)

    to_thread_mock.assert_awaited_once_with(request.execute)
    assert result == {'ok': True}


# ---------------------------------------------------------------------------
# TaskService.save_generated_task
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_generated_task_one_time_creates_no_definition():
    repository = AsyncMock()
    service = make_task_service(repository=repository)
    service.resolve_task_list_id = AsyncMock(return_value='@default')
    service.create_task = AsyncMock(return_value={'id': 'gtask-1', 'title': 'Buy milk'})

    task = GeneratedTask(title='Buy milk')

    result = await service.save_generated_task(task)

    assert result.task_definition_id is None
    repository.create_definition.assert_not_called()


@pytest.mark.asyncio
async def test_save_generated_task_recurring_creates_definition_and_maps_occurrence():
    repository = AsyncMock()
    created_definition = TaskDefinition(
        id='def-1', google_task_list_id='@default', title='Take out trash',
        recurrence=['RRULE:FREQ=WEEKLY;BYDAY=TH'])
    repository.create_definition = AsyncMock(return_value=created_definition)
    repository.create_occurrence_if_missing = AsyncMock(return_value=(
        TaskOccurrence(
            id='occ-1', task_definition_id='def-1',
            scheduled_for=datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc)),
        True))
    repository.update_definition = AsyncMock(side_effect=lambda d: d)

    service = make_task_service(repository=repository)
    service.resolve_task_list_id = AsyncMock(return_value='@default')
    service.create_task = AsyncMock(return_value={'id': 'gtask-42', 'title': 'Take out trash'})

    from datetime import date, time
    task = GeneratedTask(
        title='Take out trash',
        due_date=date(2026, 8, 6),
        due_time=time(20, 0),
        recurrence=['RRULE:FREQ=WEEKLY;BYDAY=TH'])

    result = await service.save_generated_task(task)

    assert result.task_definition_id == 'def-1'
    repository.create_definition.assert_awaited_once()
    repository.set_occurrence_google_task_id.assert_awaited_once_with('occ-1', 'gtask-42')


@pytest.mark.asyncio
async def test_save_generated_task_invalid_recurrence_raises_before_any_write():
    repository = AsyncMock()
    service = make_task_service(repository=repository)
    service.resolve_task_list_id = AsyncMock(return_value='@default')
    service.create_task = AsyncMock()

    from datetime import date
    task = GeneratedTask(
        title='Broken recurrence',
        due_date=date(2026, 8, 6),
        recurrence=['NOT_A_VALID_RRULE_LINE'])

    with pytest.raises(InvalidTaskRecurrenceException):
        await service.save_generated_task(task)

    service.create_task.assert_not_called()
    repository.create_definition.assert_not_called()


# ---------------------------------------------------------------------------
# TaskService.poll_due_tasks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_poll_failed_google_materialization_deletes_occurrence():
    now = datetime.now(timezone.utc)
    definition = TaskDefinition(
        id='def-1', google_task_list_id='@default', title='Water plants',
        starts_at=now, recurrence=['RRULE:FREQ=DAILY;COUNT=5'],
        next_occurrence_at=now, active=True)

    repository = AsyncMock()
    repository.get_due_definitions = AsyncMock(return_value=[definition])
    occurrence = TaskOccurrence(
        id='occ-1', task_definition_id='def-1', scheduled_for=now, created_at=now)
    repository.create_occurrence_if_missing = AsyncMock(return_value=(occurrence, True))

    service = make_task_service(repository=repository)
    service.create_task = AsyncMock(side_effect=Exception('Google API error'))

    result = await service.poll_due_tasks()

    repository.delete_occurrence.assert_awaited_once_with('occ-1')
    assert result.failures == 1
    assert result.occurrences_created == 0


@pytest.mark.asyncio
async def test_poll_catch_up_limit_honored():
    now = datetime.now(timezone.utc)
    definition = TaskDefinition(
        id='def-1', google_task_list_id='@default', title='Daily check',
        starts_at=now - timedelta(days=10), recurrence=['RRULE:FREQ=DAILY'],
        next_occurrence_at=now - timedelta(days=10), active=True)

    repository = AsyncMock()
    repository.get_due_definitions = AsyncMock(return_value=[definition])

    created = []

    async def fake_create_occurrence(occ):
        created.append(occ)
        return (TaskOccurrence(
            id=f'occ-{len(created)}', task_definition_id=occ.task_definition_id,
            scheduled_for=occ.scheduled_for, created_at=occ.created_at), True)

    repository.create_occurrence_if_missing = AsyncMock(side_effect=fake_create_occurrence)

    service = make_task_service(repository=repository)
    service.create_task = AsyncMock(return_value={'id': 'gtask-x'})

    result = await service.poll_due_tasks(catch_up_limit=3)

    assert result.occurrences_created == 3
    assert repository.create_occurrence_if_missing.await_count == 3


@pytest.mark.asyncio
async def test_poll_exhausted_recurrence_deactivates_definition():
    now = datetime.now(timezone.utc)
    definition = TaskDefinition(
        id='def-1', google_task_list_id='@default', title='One more time',
        starts_at=now - timedelta(days=1), recurrence=['RRULE:FREQ=DAILY;COUNT=1'],
        next_occurrence_at=now - timedelta(days=1), active=True)

    repository = AsyncMock()
    repository.get_due_definitions = AsyncMock(return_value=[definition])
    occurrence = TaskOccurrence(
        id='occ-1', task_definition_id='def-1',
        scheduled_for=definition.next_occurrence_at, created_at=now)
    repository.create_occurrence_if_missing = AsyncMock(return_value=(occurrence, True))

    updated = []

    async def fake_update_definition(d):
        updated.append(d)
        return d

    repository.update_definition = AsyncMock(side_effect=fake_update_definition)

    service = make_task_service(repository=repository)
    service.create_task = AsyncMock(return_value={'id': 'gtask-x'})

    result = await service.poll_due_tasks()

    assert result.definitions_exhausted == 1
    assert updated[-1].active is False


@pytest.mark.asyncio
async def test_poll_one_failing_definition_does_not_stop_others():
    now = datetime.now(timezone.utc)
    def_1 = TaskDefinition(
        id='def-1', google_task_list_id='@default', title='A',
        starts_at=now, recurrence=['RRULE:FREQ=DAILY;COUNT=2'],
        next_occurrence_at=now, active=True)
    def_2 = TaskDefinition(
        id='def-2', google_task_list_id='@default', title='B',
        starts_at=now, recurrence=['RRULE:FREQ=DAILY;COUNT=2'],
        next_occurrence_at=now, active=True)

    repository = AsyncMock()
    repository.get_due_definitions = AsyncMock(return_value=[def_1, def_2])

    async def fake_create_occurrence(occ):
        if occ.task_definition_id == 'def-1':
            raise Exception('Mongo failure')
        return (TaskOccurrence(
            id='occ-2', task_definition_id='def-2',
            scheduled_for=occ.scheduled_for, created_at=occ.created_at), True)

    repository.create_occurrence_if_missing = AsyncMock(side_effect=fake_create_occurrence)

    service = make_task_service(repository=repository)
    service.create_task = AsyncMock(return_value={'id': 'gtask-x'})

    result = await service.poll_due_tasks()

    assert result.failures == 1
    assert result.occurrences_created == 1


@pytest.mark.asyncio
async def test_poll_definition_limit_clamped_to_maximum():
    repository = AsyncMock()
    repository.get_due_definitions = AsyncMock(return_value=[])

    service = make_task_service(repository=repository)

    await service.poll_due_tasks(definition_limit=10_000, catch_up_limit=10_000)

    args, _ = repository.get_due_definitions.call_args
    assert args[1] == 200


# ---------------------------------------------------------------------------
# TaskService.create_task_dependency
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_task_dependency_requires_both_definitions_exist():
    repository = AsyncMock()
    repository.get_definition = AsyncMock(side_effect=[
        TaskDefinition(id='def-1', google_task_list_id='x', title='A'),
        None,
    ])

    service = make_task_service(repository=repository)

    with pytest.raises(TaskDependencyValidationException):
        await service.create_task_dependency('def-1', 'def-2')


# ---------------------------------------------------------------------------
# TaskService.get_task_summary
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_task_summary_reads_every_google_task_list():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[
        {'id': 'list-1', 'title': 'Personal'},
        {'id': 'list-2', 'title': 'Work'},
    ])
    service.get_tasks = AsyncMock(return_value=[])

    await service.get_task_summary()

    assert service.get_tasks.await_count == 2


@pytest.mark.asyncio
async def test_get_task_summary_excludes_completed_tasks_via_show_completed_false():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': 'Personal'}])
    service.get_tasks = AsyncMock(return_value=[{'id': 't1', 'title': 'Buy milk'}])

    await service.get_task_summary()

    service.get_tasks.assert_awaited_once_with('list-1', show_completed=False)


@pytest.mark.asyncio
async def test_get_task_summary_uses_live_google_list_title_as_category():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[
        {'id': 'list-1', 'title': 'Personal'},
        {'id': 'list-2', 'title': 'Work'},
    ])

    async def fake_get_tasks(task_list_id, show_completed=False):
        if task_list_id == 'list-1':
            return [{'id': 't1', 'title': 'Buy milk'}]
        return [{'id': 't2', 'title': 'Ship report'}]

    service.get_tasks = AsyncMock(side_effect=fake_get_tasks)

    summary = await service.get_task_summary()

    assert isinstance(summary, TaskSummary)
    categories = {t.title: t.task_list for t in summary.tasks}
    assert categories == {'Buy milk': 'Personal', 'Ship report': 'Work'}


@pytest.mark.asyncio
async def test_get_task_summary_moved_task_reflects_current_list():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[
        {'id': 'list-1', 'title': 'Personal'},
        {'id': 'list-2', 'title': 'Work'},
    ])

    # Same Google task id now returned from 'Work' because it was moved there.
    service.get_tasks = AsyncMock(side_effect=[
        [],
        [{'id': 't1', 'title': 'Moved task'}],
    ])

    summary = await service.get_task_summary()

    assert len(summary.tasks) == 1
    assert summary.tasks[0].task_list == 'Work'


@pytest.mark.asyncio
async def test_get_task_summary_includes_tasks_without_due_date():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': 'Personal'}])
    service.get_tasks = AsyncMock(return_value=[{'id': 't1', 'title': 'No due date'}])

    summary = await service.get_task_summary()

    assert len(summary.tasks) == 1
    assert summary.tasks[0].due_date is None


@pytest.mark.asyncio
async def test_get_task_summary_sorts_due_tasks_ascending_then_undated_last():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': 'Personal'}])
    service.get_tasks = AsyncMock(return_value=[
        {'id': 't1', 'title': 'Later', 'due': '2026-08-20T00:00:00.000Z'},
        {'id': 't2', 'title': 'No due date'},
        {'id': 't3', 'title': 'Sooner', 'due': '2026-08-10T00:00:00.000Z'},
    ])

    summary = await service.get_task_summary()

    assert [t.title for t in summary.tasks] == ['Sooner', 'Later', 'No due date']


@pytest.mark.asyncio
async def test_get_task_summary_equal_dates_sorted_by_title():
    service = make_task_service()
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': 'Personal'}])
    service.get_tasks = AsyncMock(return_value=[
        {'id': 't1', 'title': 'Zebra task', 'due': '2026-08-10T00:00:00.000Z'},
        {'id': 't2', 'title': 'Alpha task', 'due': '2026-08-10T00:00:00.000Z'},
    ])

    summary = await service.get_task_summary()

    assert [t.title for t in summary.tasks] == ['Alpha task', 'Zebra task']


@pytest.mark.asyncio
async def test_get_task_summary_does_not_write_to_mongo_repository():
    repository = AsyncMock()
    service = make_task_service(repository=repository)
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': 'Personal'}])
    service.get_tasks = AsyncMock(return_value=[{'id': 't1', 'title': 'Buy milk'}])

    await service.get_task_summary()

    assert repository.method_calls == []


# ---------------------------------------------------------------------------
# TaskService.send_task_summary_email
# ---------------------------------------------------------------------------

def _sib_service(**overrides):
    sib_client = AsyncMock()
    config = TaskConfig(preferences={'email': 'me@example.com'})
    service = make_task_service(sib_client=sib_client, config=config, **overrides)
    return service, sib_client


@pytest.mark.asyncio
async def test_send_task_summary_email_uses_existing_sib_client():
    service, sib_client = _sib_service()
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': 'Personal'}])
    service.get_tasks = AsyncMock(return_value=[{'id': 't1', 'title': 'Buy milk'}])

    summary = await service.send_task_summary_email()

    sib_client.send_email.assert_awaited_once()
    kwargs = sib_client.send_email.await_args.kwargs
    assert kwargs['recipient'] == 'me@example.com'
    assert kwargs['subject'] == 'Task Summary'
    assert isinstance(summary, TaskSummary)
    assert summary.tasks[0].title == 'Buy milk'


@pytest.mark.asyncio
async def test_send_task_summary_email_html_has_expected_columns_and_escapes_values():
    service, sib_client = _sib_service()
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': '<Home>'}])
    service.get_tasks = AsyncMock(return_value=[
        {'id': 't1', 'title': '<script>alert(1)</script>'},
    ])

    await service.send_task_summary_email()

    html_body = sib_client.send_email.await_args.kwargs['html_body']

    assert '<th align="left">Task</th>' in html_body
    assert '<th align="left">Category</th>' in html_body
    assert '<th align="left">Due</th>' in html_body
    assert '<script>alert(1)</script>' not in html_body
    assert '&lt;script&gt;' in html_body
    assert '&lt;Home&gt;' in html_body


@pytest.mark.asyncio
async def test_send_task_summary_email_formats_due_date_and_dash_for_none():
    service, sib_client = _sib_service()
    service.get_task_lists = AsyncMock(return_value=[{'id': 'list-1', 'title': 'Personal'}])
    service.get_tasks = AsyncMock(return_value=[
        {'id': 't1', 'title': 'Dated', 'due': '2026-08-10T00:00:00.000Z'},
        {'id': 't2', 'title': 'Undated'},
    ])

    await service.send_task_summary_email()

    html_body = sib_client.send_email.await_args.kwargs['html_body']
    assert 'Aug 10, 2026' in html_body
    assert '<td>-</td>' in html_body


def test_build_task_summary_email_html_highlights_only_overdue_rows():
    summary = TaskSummary(
        generated_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        tasks=[
            TaskSummaryItem(
                id='overdue',
                title='Overdue task',
                task_list='Personal',
                due_date=date(2026, 8, 6),
            ),
            TaskSummaryItem(
                id='today',
                title='Due today',
                task_list='Personal',
                due_date=date(2026, 8, 7),
            ),
            TaskSummaryItem(
                id='future',
                title='Due later',
                task_list='Personal',
                due_date=date(2026, 8, 8),
            ),
            TaskSummaryItem(
                id='undated',
                title='No due date',
                task_list='Personal',
                due_date=None,
            ),
        ],
    )

    html_body = _build_task_summary_email_html(
        summary,
        current_local_date=date(2026, 8, 7),
    )

    assert html_body.count('background-color: #fdecec;') == 1
    assert html_body.count('font-weight: 600;') == 1
    assert 'Overdue task' in html_body
    assert 'Due today' in html_body
    assert 'Due later' in html_body
    assert 'No due date' in html_body
    assert '<tr style="background-color: #fdecec;">' in html_body
    assert '<td style="font-weight: 600;">Aug 06, 2026</td>' in html_body


@pytest.mark.asyncio
async def test_send_task_summary_email_empty_state():
    service, sib_client = _sib_service()
    service.get_task_lists = AsyncMock(return_value=[])

    summary = await service.send_task_summary_email()

    sib_client.send_email.assert_awaited_once_with(
        recipient='me@example.com',
        subject='Task Summary',
        html_body='No incomplete tasks.')
    assert summary.tasks == []
