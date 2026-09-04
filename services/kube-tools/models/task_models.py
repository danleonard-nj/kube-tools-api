from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TaskConfig(BaseModel):
    # Supported keys: home, time_zone, default_task_list, default_task_time
    preferences: dict[str, str] = Field(default_factory=dict)


class TaskListSummary(BaseModel):
    id: str
    title: str


class GeneratedTask(BaseModel):
    title: str
    notes: str | None = None
    task_list: str | None = None

    due_date: date | None = None
    due_time: time | None = None
    time_zone: str = "America/New_York"

    recurrence: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def _validate_recurrence_requires_due_date(self) -> 'GeneratedTask':
        if self.recurrence and self.due_date is None:
            raise ValueError(
                'A recurring task requires a concrete initial due_date')
        return self


class GoogleTaskPayload(BaseModel):
    title: str
    notes: str | None = None
    due: str | None = None
    status: Literal["needsAction", "completed"] = "needsAction"


class TaskDefinition(BaseModel):
    id: str | None = None

    google_task_list_id: str

    title: str
    notes: str | None = None

    starts_at: datetime | None = None
    recurrence: list[str] = Field(default_factory=list)

    next_occurrence_at: datetime | None = None
    last_materialized_at: datetime | None = None

    active: bool = True

    created_at: datetime | None = None
    updated_at: datetime | None = None


class TaskOccurrence(BaseModel):
    id: str | None = None

    task_definition_id: str
    google_task_id: str | None = None

    scheduled_for: datetime
    completed_at: datetime | None = None

    triggered_by_occurrence_id: str | None = None

    created_at: datetime | None = None


class TaskDependency(BaseModel):
    id: str | None = None

    predecessor_task_definition_id: str
    successor_task_definition_id: str

    trigger: Literal["completed"] = "completed"
    delay_seconds: int = 0

    created_at: datetime | None = None

    @model_validator(mode='after')
    def _validate_dependency(self) -> 'TaskDependency':
        if self.delay_seconds < 0:
            raise ValueError('delay_seconds cannot be negative')
        if self.predecessor_task_definition_id == self.successor_task_definition_id:
            raise ValueError(
                'A task definition cannot depend directly on itself')
        return self


class SavedTaskResult(BaseModel):
    task: dict
    task_definition_id: str | None = None


class TaskPollResult(BaseModel):
    definitions_processed: int = 0
    occurrences_created: int = 0
    occurrences_skipped: int = 0
    definitions_exhausted: int = 0
    failures: int = 0


class TaskSummaryItem(BaseModel):
    id: str
    title: str
    task_list: str

    due_date: date | None = None
    notes: str | None = None


class TaskSummary(BaseModel):
    generated_at: datetime
    tasks: list[TaskSummaryItem]
