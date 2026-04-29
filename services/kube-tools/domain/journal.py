"""Journal domain models."""
from __future__ import annotations

import enum
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class JournalEntryStatus(enum.StrEnum):
    CREATED = 'created'
    QUEUED = 'queued'
    PROCESSING = 'processing'
    PROCESSED = 'processed'
    FAILED = 'failed'


class JournalSource(enum.StrEnum):
    VOICE = 'voice'
    TEXT = 'text'


class PolishMode(enum.StrEnum):
    GRAMMAR = 'grammar'
    ORGANIZE = 'organize'
    CONCISE = 'concise'
    EXPAND = 'expand'
    TONE = 'tone'


class JournalSegment(BaseModel):
    clip_id: Optional[str] = None
    started_at: Optional[Any] = None
    duration_seconds: Optional[float] = None
    transcript: str = ''


class JournalMood(BaseModel):
    score: Optional[int] = None
    label: Optional[str] = None
    confidence: Optional[float] = None


class JournalRiskFlags(BaseModel):
    crisis_language: bool = False
    medical_concern: bool = False


class JournalAnalysis(BaseModel):
    summary_short: Optional[str] = None
    summary_detailed: Optional[str] = None
    key_events: List[str] = Field(default_factory=list)
    people_mentioned: List[str] = Field(default_factory=list)
    places_or_contexts: List[str] = Field(default_factory=list)
    stressors: List[str] = Field(default_factory=list)
    positive_developments: List[str] = Field(default_factory=list)
    open_loops: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    mood: Optional[JournalMood] = None
    symptoms: List[str] = Field(default_factory=list)
    action_items: List[str] = Field(default_factory=list)
    risk_flags: Optional[JournalRiskFlags] = None


class JournalProcessingMetadata(BaseModel):
    requested_at: Optional[Any] = None
    started_at: Optional[Any] = None
    completed_at: Optional[Any] = None
    failed_at: Optional[Any] = None
    error: Optional[str] = None
    attempt_count: int = 0


class JournalEntry(BaseModel):
    entry_id: str
    created_at: Any
    updated_at: Any
    title: Optional[str] = None
    is_manual_title: bool = False
    source: str = JournalSource.VOICE
    status: str = JournalEntryStatus.CREATED
    segments: List[JournalSegment] = Field(default_factory=list)
    raw_transcript: str = ''
    cleaned_transcript: Optional[str] = None
    pre_polish_transcript: Optional[str] = None
    analysis: Optional[JournalAnalysis] = None
    processing: Optional[JournalProcessingMetadata] = None

    def get_selector(self) -> dict:
        return {'entry_id': self.entry_id}

    @staticmethod
    def from_entity(data: dict) -> Optional['JournalEntry']:
        if not data:
            return None
        data.pop('_id', None)
        return JournalEntry.model_validate(data)
