"""Audio format utilities: MIME type lookup and size estimation."""

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
    """Estimate encoded audio size in MB without performing a real export."""
    duration_sec = len(audio_segment) / 1000.0
    sample_rate = audio_segment.frame_rate
    channels = audio_segment.channels

    if format == 'flac':
        uncompressed_mb = (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)
        return uncompressed_mb * 0.55
    if format == 'wav':
        return (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)
    if format == 'mp3':
        return (128 * 1024 * duration_sec) / (8 * 1024 * 1024)
    return (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)
