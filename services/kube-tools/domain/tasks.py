"""Domain constants, exceptions and pure recurrence/date helpers for the Google Tasks feature."""
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from dateutil.rrule import rruleset, rrulestr

from models.task_models import GeneratedTask

SAMPLE_GENERATED_TASK_JSON = '''{
    "title": "Take the trash outside",
    "notes": null,
    "task_list": "Default",
    "due_date": "2026-08-06",
    "due_time": "20:00:00",
    "time_zone": "America/New_York",
    "recurrence": ["RRULE:FREQ=WEEKLY;BYDAY=TH"]
}'''


class TaskListNotFoundException(Exception):
    def __init__(self, list_name: str, *args: object) -> None:
        super().__init__(
            f"No Google task list with the title '{list_name}' could be found")


class InvalidTaskRecurrenceException(Exception):
    def __init__(self, message: str, *args: object) -> None:
        super().__init__(message)


class NoTaskInputProvidedException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(
            'No valid input provided. Supply either prompt, image_bytes or text.')


class TaskSaveCompensationException(Exception):
    def __init__(self, message: str, *args: object) -> None:
        super().__init__(message)


class TaskDependencyValidationException(Exception):
    def __init__(self, message: str, *args: object) -> None:
        super().__init__(message)


def build_start_datetime(
    task: GeneratedTask,
    default_time: time
) -> datetime:
    """Combine a generated task's due date/time into a timezone-aware local datetime."""
    if task.due_date is None:
        raise InvalidTaskRecurrenceException(
            'A recurring task requires a concrete initial due_date')

    local_time = task.due_time or default_time
    naive = datetime.combine(task.due_date, local_time)
    return naive.replace(tzinfo=ZoneInfo(task.time_zone))


def format_google_due_date(
    due_date: date | None
) -> str | None:
    if due_date is None:
        return None
    return f'{due_date.isoformat()}T00:00:00.000Z'


def parse_google_due_date(
    due: str | None
) -> date | None:
    """Parse a Google Tasks RFC3339 'due' timestamp into a plain date."""
    if not due:
        return None
    return datetime.fromisoformat(due.replace('Z', '+00:00')).date()


def parse_recurrence(
    recurrence: list[str],
    starts_at: datetime
) -> rruleset:
    """Validate and build an RFC 5545 rule set from newline-joined recurrence lines."""
    recurrence_text = '\n'.join(recurrence)

    try:
        return rrulestr(
            recurrence_text,
            dtstart=starts_at,
            forceset=True)
    except (ValueError, TypeError) as e:
        raise InvalidTaskRecurrenceException(
            f'Invalid recurrence definition: {e}') from e


def calculate_next_occurrence(
    recurrence: list[str],
    starts_at: datetime,
    after: datetime
) -> datetime | None:
    rule_set = parse_recurrence(recurrence, starts_at)
    return rule_set.after(after, inc=False)
