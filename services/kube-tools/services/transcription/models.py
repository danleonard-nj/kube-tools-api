"""Shared data classes for the transcription pipeline."""

from typing import Optional
from dataclasses import dataclass
from pydub import AudioSegment


@dataclass
class AudioChunk:
    """
    Represents a chunk of audio data with metadata.

    Attributes:
        audio_segment: The actual audio data for this chunk
        logical_start_ms: Start time of the content (without overlap)
        logical_end_ms: End time of the content (without overlap)
        actual_start_ms: Start time including overlap padding
        actual_end_ms: End time including overlap padding
        chunk_index: Index of this chunk in the sequence
    """
    audio_segment: AudioSegment
    logical_start_ms: float
    logical_end_ms: float
    actual_start_ms: float
    actual_end_ms: float
    chunk_index: int


@dataclass
class WordToken:
    """
    Represents a single word token with timing and speaker information.

    This is the source of truth for word-level timing in the transcription.

    Attributes:
        text: The word text (including punctuation)
        start: Start time in seconds
        end: End time in seconds
        speaker: Optional speaker label (e.g., 'Speaker 1')
    """
    text: str
    start: float
    end: float
    speaker: Optional[str] = None
