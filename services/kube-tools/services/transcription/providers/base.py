"""Provider interface + result types for speech-to-text backends."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class Word:
    """Single recognised word in **chunk-local** seconds."""
    text: str
    start: float
    end: float
    speaker: Optional[str] = None


@dataclass
class TranscriptionResult:
    """Result of transcribing a single chunk.

    Timestamps in ``words`` and ``segments`` are **chunk-local** seconds
    (relative to the audio bytes passed to ``transcribe``).  The
    transcription service maps them to global seconds via the chunk's
    excision map.
    """
    text: str
    confidence: Optional[float] = None
    duration_ms: int = 0
    words: Optional[List[Word]] = None
    # Optional segment list (chunk-local seconds) — used downstream for
    # diarised resegmentation when the provider supplies them.
    segments: Optional[List[Dict[str, Any]]] = None
    # Free-form provider metadata (model name, request id, etc.).
    metadata: Dict[str, Any] = field(default_factory=dict)


class TranscriptionProvider(Protocol):
    """Minimal async STT provider interface."""

    name: str

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        diarize: bool = False,
    ) -> TranscriptionResult:
        ...
