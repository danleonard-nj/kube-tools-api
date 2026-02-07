"""Duration-based audio chunking with gap-free logical tiling."""

from typing import List

from pydub import AudioSegment

from framework.logger import get_logger
from services.transcription.models import AudioChunk

logger = get_logger(__name__)


def chunk_by_duration(
    audio_segment: AudioSegment,
    chunk_duration_ms: int = 60_000,
    overlap_ms: int = 1_500
) -> List[AudioChunk]:
    """
    Split audio into gap-free chunks by duration with leading overlap.

    Logical windows tile the audio without gaps:
        chunk 0: logical [0, chunk_duration_ms)
        chunk 1: logical [chunk_duration_ms, 2*chunk_duration_ms)
        ...
    Each chunk's *actual* extraction starts ``overlap_ms`` earlier than its
    logical start (clamped to 0 for the first chunk) so that the model has
    context across boundaries.

    Args:
        audio_segment: Audio to chunk
        chunk_duration_ms: Target chunk duration in ms (default 60 000)
        overlap_ms: Leading overlap in ms (default 1 500)

    Returns:
        List of AudioChunk objects
    """
    audio_length_ms = len(audio_segment)
    chunks: List[AudioChunk] = []

    logger.info(f"Chunking audio by duration: {chunk_duration_ms}ms chunks with {overlap_ms}ms overlap")

    chunk_index = 0
    logical_start = 0

    while logical_start < audio_length_ms:
        logical_end = min(logical_start + chunk_duration_ms, audio_length_ms)

        # actual_start reaches back by overlap_ms (clamped to 0)
        actual_start = max(0, logical_start - overlap_ms)
        actual_end = logical_end  # no trailing overlap needed

        chunk_audio = audio_segment[actual_start:actual_end]

        chunks.append(AudioChunk(
            audio_segment=chunk_audio,
            logical_start_ms=logical_start,
            logical_end_ms=logical_end,
            actual_start_ms=actual_start,
            actual_end_ms=actual_end,
            chunk_index=chunk_index
        ))

        logger.info(f"Chunk {chunk_index}: logical=[{logical_start}-{logical_end}]ms "
                    f"actual=[{actual_start}-{actual_end}]ms")

        chunk_index += 1
        # next chunk starts exactly where this one ends — no gaps
        logical_start = logical_end

    logger.info(f"Created {len(chunks)} duration-based chunks")
    return chunks
