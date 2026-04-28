"""Journal domain models."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional

from framework.serialization import Serializable


class JournalEntryStatus(enum.StrEnum):
    CREATED = 'created'
    QUEUED = 'queued'
    PROCESSING = 'processing'
    PROCESSED = 'processed'
    FAILED = 'failed'


class JournalSource(enum.StrEnum):
    VOICE = 'voice'
    TEXT = 'text'


class JournalSegment(Serializable):
    def __init__(
        self,
        clip_id: Optional[str],
        started_at: Any,
        duration_seconds: Optional[float],
        transcript: str,
    ):
        self.clip_id = clip_id
        self.started_at = started_at
        self.duration_seconds = duration_seconds
        self.transcript = transcript

    @staticmethod
    def from_entity(data: dict) -> 'JournalSegment':
        return JournalSegment(
            clip_id=data.get('clip_id'),
            started_at=data.get('started_at'),
            duration_seconds=data.get('duration_seconds'),
            transcript=data.get('transcript', ''),
        )


class JournalMood(Serializable):
    def __init__(
        self,
        score: Optional[int],
        label: Optional[str],
        confidence: Optional[float],
    ):
        self.score = score
        self.label = label
        self.confidence = confidence

    @staticmethod
    def from_entity(data: dict) -> Optional['JournalMood']:
        if not data:
            return None
        return JournalMood(
            score=data.get('score'),
            label=data.get('label'),
            confidence=data.get('confidence'),
        )


class JournalRiskFlags(Serializable):
    def __init__(
        self,
        crisis_language: bool = False,
        medical_concern: bool = False,
    ):
        self.crisis_language = crisis_language
        self.medical_concern = medical_concern

    @staticmethod
    def from_entity(data: dict) -> Optional['JournalRiskFlags']:
        if not data:
            return None
        return JournalRiskFlags(
            crisis_language=data.get('crisis_language', False),
            medical_concern=data.get('medical_concern', False),
        )


class JournalAnalysis(Serializable):
    def __init__(
        self,
        summary: Optional[str],
        bullets: List[str],
        themes: List[str],
        mood: Optional[JournalMood],
        symptoms: List[str],
        action_items: List[str],
        risk_flags: Optional[JournalRiskFlags],
    ):
        self.summary = summary
        self.bullets = bullets or []
        self.themes = themes or []
        self.mood = mood
        self.symptoms = symptoms or []
        self.action_items = action_items or []
        self.risk_flags = risk_flags

    def to_dict(self) -> dict:
        return super().to_dict() | {
            'mood': self.mood.to_dict() if self.mood else None,
            'risk_flags': self.risk_flags.to_dict() if self.risk_flags else None,
        }

    @staticmethod
    def from_entity(data: dict) -> Optional['JournalAnalysis']:
        if not data:
            return None
        return JournalAnalysis(
            summary=data.get('summary'),
            bullets=data.get('bullets', []),
            themes=data.get('themes', []),
            mood=JournalMood.from_entity(data['mood']) if data.get('mood') else None,
            symptoms=data.get('symptoms', []),
            action_items=data.get('action_items', []),
            risk_flags=JournalRiskFlags.from_entity(data['risk_flags']) if data.get('risk_flags') else None,
        )


class JournalProcessingMetadata(Serializable):
    def __init__(
        self,
        requested_at: Any,
        started_at: Any = None,
        completed_at: Any = None,
        failed_at: Any = None,
        error: Optional[str] = None,
        attempt_count: int = 0,
    ):
        self.requested_at = requested_at
        self.started_at = started_at
        self.completed_at = completed_at
        self.failed_at = failed_at
        self.error = error
        self.attempt_count = attempt_count

    @staticmethod
    def from_entity(data: dict) -> Optional['JournalProcessingMetadata']:
        if not data:
            return None
        return JournalProcessingMetadata(
            requested_at=data.get('requested_at'),
            started_at=data.get('started_at'),
            completed_at=data.get('completed_at'),
            failed_at=data.get('failed_at'),
            error=data.get('error'),
            attempt_count=data.get('attempt_count', 0),
        )


class JournalEntry(Serializable):
    def __init__(
        self,
        entry_id: str,
        created_at: Any,
        updated_at: Any,
        title: Optional[str],
        source: str,
        status: str,
        segments: List[JournalSegment],
        raw_transcript: str,
        cleaned_transcript: Optional[str] = None,
        analysis: Optional[JournalAnalysis] = None,
        processing: Optional[JournalProcessingMetadata] = None,
    ):
        self.entry_id = entry_id
        self.created_at = created_at
        self.updated_at = updated_at
        self.title = title
        self.source = source
        self.status = status
        self.segments = segments or []
        self.raw_transcript = raw_transcript
        self.cleaned_transcript = cleaned_transcript
        self.analysis = analysis
        self.processing = processing

    def get_selector(self) -> dict:
        return {'entry_id': self.entry_id}

    def to_dict(self) -> dict:
        return super().to_dict() | {
            'segments': [s.to_dict() for s in self.segments],
            'analysis': self.analysis.to_dict() if self.analysis else None,
            'processing': self.processing.to_dict() if self.processing else None,
        }

    @staticmethod
    def from_entity(data: dict) -> Optional['JournalEntry']:
        if not data:
            return None
        return JournalEntry(
            entry_id=data.get('entry_id'),
            created_at=data.get('created_at'),
            updated_at=data.get('updated_at'),
            title=data.get('title'),
            source=data.get('source', JournalSource.VOICE),
            status=data.get('status', JournalEntryStatus.CREATED),
            segments=[JournalSegment.from_entity(s) for s in data.get('segments', [])],
            raw_transcript=data.get('raw_transcript', ''),
            cleaned_transcript=data.get('cleaned_transcript'),
            analysis=JournalAnalysis.from_entity(data['analysis']) if data.get('analysis') else None,
            processing=JournalProcessingMetadata.from_entity(data['processing']) if data.get('processing') else None,
        )
