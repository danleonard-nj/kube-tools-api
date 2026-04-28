"""Pluggable speech-to-text providers.

Each provider takes encoded audio bytes (typically FLAC/WAV) for a single
chunk and returns a :class:`TranscriptionResult` with chunk-local timing.
The transcription service is responsible for globalising timestamps via
the chunk's excision map.
"""

from services.transcription.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
    Word,
)

__all__ = [
    "TranscriptionProvider",
    "TranscriptionResult",
    "Word",
]
