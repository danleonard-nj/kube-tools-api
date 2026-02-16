"""Audio format utilities: MIME type lookup, size estimation, single-shot safety check."""

from pydub import AudioSegment

from framework.logger import get_logger

logger = get_logger(__name__)


def get_audio_mime_type(filename: str) -> str:
    """Get the appropriate MIME type for an audio file based on its extension.

    Falls back to ``audio/mpeg`` for unrecognised extensions, which is the
    safest default for the OpenAI transcription API.
    """
    extension = filename.lower().split('.')[-1] if '.' in filename else ''

    mime_types = {
        'mp3': 'audio/mpeg',
        'mp4': 'audio/mp4',
        'm4a': 'audio/mp4',
        'wav': 'audio/wav',
        'flac': 'audio/flac',
        'ogg': 'audio/ogg',
        'oga': 'audio/ogg',
        'webm': 'audio/webm',
        'mpeg': 'audio/mpeg',
        'mpga': 'audio/mpeg',
    }

    return mime_types.get(extension, 'audio/mpeg')


def estimate_encoded_size_mb(
    audio_segment: AudioSegment,
    format: str = 'flac',
) -> float:
    """Estimate encoded audio size in MB without performing a real export.

    Args:
        audio_segment: Audio to estimate.
        format: Target format (``'flac'``, ``'wav'``, ``'mp3'``).

    Returns:
        Estimated size in MB.
    """
    duration_sec = len(audio_segment) / 1000.0
    sample_rate = audio_segment.frame_rate
    channels = audio_segment.channels

    if format == 'flac':
        # FLAC typically achieves 50-60% compression ratio for speech
        uncompressed_mb = (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)
        return uncompressed_mb * 0.55  # Conservative estimate
    elif format == 'wav':
        return (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)
    elif format == 'mp3':
        return (128 * 1024 * duration_sec) / (8 * 1024 * 1024)
    else:
        # Conservative: assume uncompressed
        return (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)


def is_single_shot_safe(
    audio_segment: AudioSegment,
    max_size_mb: float = 22.0,
    source_format: str = '',
) -> tuple[bool, str]:
    """Determine if audio can be safely transcribed in a single API call.

    Uses estimation only — no real export.  The actual export happens later
    when sending to the API, so there is no need to do it twice.  Previous
    versions performed a real export here, but pydub/ffmpeg silently produced
    0-byte files for WebM/Opus input, wasting ~600 ms per request.

    WebM files use WAV export for compatibility (FLAC from Opus can fail).
    Default 22 MB leaves headroom below the 25 MB API limit.

    Args:
        audio_segment: Audio to check.
        max_size_mb: Maximum safe size in MB.
        source_format: Original file extension (used to detect WebM/Opus).

    Returns:
        Tuple of (is_safe, export_format).
        - is_safe: True if single-shot is safe.
        - export_format: ``'flac'`` or ``'wav'``.
    """
    export_format = 'wav' if source_format.lower() == 'webm' else 'flac'
    estimated_mb = estimate_encoded_size_mb(audio_segment, export_format)
    is_safe = estimated_mb < max_size_mb

    logger.info(
        "Size gate: estimated %s size %.1fMB (limit %.1fMB) → %s",
        export_format.upper(), estimated_mb, max_size_mb,
        'single-shot' if is_safe else 'chunking',
    )

    return is_safe, export_format
