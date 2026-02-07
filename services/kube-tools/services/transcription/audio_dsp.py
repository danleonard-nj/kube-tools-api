"""DSP helpers: silence detection, comfort-noise injection, MIME types, size checks."""

import io
from typing import Tuple

import numpy as np
from pydub import AudioSegment

from framework.logger import get_logger

logger = get_logger(__name__)


def get_audio_mime_type(filename: str) -> str:
    """Get the appropriate MIME type for audio file based on extension."""
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
        'mpga': 'audio/mpeg'
    }

    return mime_types.get(extension, 'audio/mpeg')  # Default to mpeg if unknown


def generate_comfort_noise(num_samples: int, amplitude_db: float = -60) -> np.ndarray:
    """
    Generate white comfort noise - fast vectorized implementation.

    At very low levels (-60dB), spectral color doesn't matter, so we use
    simple white noise instead of pink noise for performance.

    Args:
        num_samples: Number of samples to generate
        amplitude_db: Amplitude in dB relative to full scale (default -60 dB)

    Returns:
        numpy array of white noise samples (float32, range -1 to 1)
    """
    # Vectorized white noise generation (much faster than pink noise)
    noise = np.random.randn(num_samples).astype(np.float32)

    # Normalize to [-1, 1] range
    noise = noise / np.abs(noise).max()

    # Apply amplitude adjustment
    amplitude = 10 ** (amplitude_db / 20)
    noise = noise * amplitude

    return noise


def detect_long_silences(
    samples: np.ndarray,
    sample_rate: int,
    silence_thresh_dbfs: float = -45,
    min_silence_ms: int = 1500,
    window_ms: int = 100
) -> np.ndarray:
    """
    Detect long silence regions using fast O(N) pure-numpy operations.

    Uses cumulative-sum windowed RMS (no scipy, no convolve), converts to
    dBFS with epsilon, then applies run-length filtering to keep only
    silence runs >= min_silence_ms.

    Args:
        samples: Audio samples as numpy array (mono, any numeric dtype)
        sample_rate: Sample rate in Hz
        silence_thresh_dbfs: dBFS threshold for silence (default -45)
        min_silence_ms: Minimum silence duration to detect (default 1500ms)
        window_ms: Window size for RMS computation (default 100ms)

    Returns:
        Boolean mask of same length as samples indicating silent regions
    """
    n = len(samples)
    if n == 0:
        return np.zeros(0, dtype=bool)

    # Normalize to float32 in [-1, 1]
    if np.issubdtype(samples.dtype, np.integer):
        # Scale by the dtype's max (works for int16, int32, etc.)
        samples = samples.astype(np.float32) / float(np.iinfo(samples.dtype).max)
    else:
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        max_abs = np.abs(samples).max()
        if max_abs > 1.0:
            samples = samples / max_abs

    # Guard window_size >= 1
    window_size = max(1, int(window_ms * sample_rate / 1000))

    # --- Windowed RMS via cumulative sum (O(N), no convolve) ---
    squared = samples * samples
    cumsum = np.empty(n + 1, dtype=np.float64)
    cumsum[0] = 0.0
    np.cumsum(squared, out=cumsum[1:])

    half_w = window_size // 2
    # Build left/right index arrays (clipped to valid range)
    idx = np.arange(n)
    left = np.clip(idx - half_w, 0, n)
    right = np.clip(idx - half_w + window_size, 0, n)
    counts = (right - left).astype(np.float64)
    counts[counts == 0] = 1.0  # prevent division by zero

    mean_sq = (cumsum[right] - cumsum[left]) / counts
    rms = np.sqrt(mean_sq)

    # --- Convert to dBFS safely ---
    epsilon = 1e-10
    dbfs = 20.0 * np.log10(rms + epsilon)

    # Boolean mask: True where below silence threshold
    silence_mask = dbfs < silence_thresh_dbfs

    # --- Run-length filtering: keep only runs >= min_samples ---
    min_samples = max(1, int(min_silence_ms * sample_rate / 1000))

    # Find transitions: prepend/append False sentinels
    padded = np.empty(n + 2, dtype=bool)
    padded[0] = False
    padded[1:-1] = silence_mask
    padded[-1] = False

    diff = np.diff(padded.astype(np.int8))
    # starts: where diff == 1  (transition False->True)
    # ends:   where diff == -1 (transition True->False)
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)

    filtered_mask = np.zeros(n, dtype=bool)
    for s, e in zip(starts, ends):
        if (e - s) >= min_samples:
            filtered_mask[s:e] = True

    return filtered_mask


def estimate_encoded_size_mb(audio_segment: AudioSegment, format: str = 'flac') -> float:
    """
    Estimate encoded audio size in MB.

    Args:
        audio_segment: Audio to estimate
        format: Target format ('flac', 'wav', 'mp3')

    Returns:
        Estimated size in MB
    """
    duration_sec = len(audio_segment) / 1000.0
    sample_rate = audio_segment.frame_rate
    channels = audio_segment.channels

    if format == 'flac':
        # FLAC typically achieves 50-60% compression ratio for speech
        uncompressed_mb = (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)
        return uncompressed_mb * 0.55  # Conservative estimate
    elif format == 'wav':
        # WAV is uncompressed
        return (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)
    elif format == 'mp3':
        # Assume 128 kbps for speech
        return (128 * 1024 * duration_sec) / (8 * 1024 * 1024)
    else:
        # Conservative: assume uncompressed
        return (sample_rate * channels * 2 * duration_sec) / (1024 * 1024)


def is_single_shot_safe(audio_segment: AudioSegment, max_size_mb: float = 22.0) -> Tuple[bool, str]:
    """
    Determine if audio can be safely transcribed in a single shot.

    Performs an actual FLAC export to BytesIO and checks the real byte length.
    The estimate function is used as a fast pre-check, but the real export is
    the final gate.  Default 22 MB leaves headroom for multipart container
    wrapping and metadata below the 25 MB API limit.

    Args:
        audio_segment: Audio to check
        max_size_mb: Maximum safe size in MB (default 22.0 to leave margin below 25MB)

    Returns:
        Tuple of (is_safe, format_to_use)
        - is_safe: True if single-shot is safe
        - format_to_use: 'flac'
    """
    # Fast estimate pre-check — skip expensive export when clearly safe/unsafe
    estimated_mb = estimate_encoded_size_mb(audio_segment, 'flac')
    if estimated_mb > max_size_mb * 1.5:
        logger.info(f"Estimated FLAC size {estimated_mb:.1f}MB far exceeds {max_size_mb}MB, skipping export check")
        return False, 'flac'

    # Real-size gate: actually export FLAC and measure
    buf = io.BytesIO()
    audio_segment.export(buf, format='flac')
    actual_bytes = buf.tell()
    actual_mb = actual_bytes / (1024 * 1024)

    logger.info(f"Actual FLAC size: {actual_mb:.2f}MB (estimate was {estimated_mb:.1f}MB, limit {max_size_mb}MB)")

    if actual_mb < max_size_mb:
        return True, 'flac'

    logger.info(f"Actual FLAC size {actual_mb:.2f}MB >= {max_size_mb}MB, will use chunking")
    return False, 'flac'


def inject_comfort_noise(
    audio_segment: AudioSegment,
    noise_level_db: float = -60,
    silence_thresh_dbfs: float = -45,
    min_silence_ms: int = 1500
) -> AudioSegment:
    """
    Inject low-level comfort noise into LONG silent portions to keep encoder alive.

    Uses fast vectorized operations and only targets silences >= min_silence_ms.
    White noise at -60dB is imperceptible and prevents premature transcription termination.

    Handles any channel count: silence is detected on a mono mixdown (mean of
    all channels), but noise is injected into every channel.  Arithmetic is done
    in int32 and clipped back to int16.

    Args:
        audio_segment: The audio to process
        noise_level_db: Comfort noise amplitude in dB (default -60, very quiet)
        silence_thresh_dbfs: dBFS threshold to detect silence (default -45)
        min_silence_ms: Minimum silence duration to inject noise (default 1500ms)

    Returns:
        Modified AudioSegment with comfort noise injected in long silent regions
    """
    sample_rate = audio_segment.frame_rate
    channels = audio_segment.channels

    logger.info(f"Checking for long silences (>={min_silence_ms}ms, thresh={silence_thresh_dbfs}dBFS)")

    # Convert to numpy array (int16)
    raw_samples = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)

    # Total number of per-channel frames
    num_frames = len(raw_samples) // channels

    # Reshape to (num_frames, channels) — works for 1, 2, or any channel count
    samples_2d = raw_samples.reshape((num_frames, channels))

    # Mono mixdown for silence detection (mean across channels)
    samples_mono = samples_2d.mean(axis=1).astype(np.float32)

    # Detect long silences using fast vectorized function
    silence_mask = detect_long_silences(
        samples_mono,
        sample_rate,
        silence_thresh_dbfs=silence_thresh_dbfs,
        min_silence_ms=min_silence_ms
    )

    silent_sample_count = int(np.sum(silence_mask))
    silent_duration_ms = silent_sample_count * 1000.0 / sample_rate

    # Count distinct silence runs for logging
    if silent_sample_count > 0:
        padded = np.empty(len(silence_mask) + 2, dtype=bool)
        padded[0] = False
        padded[1:-1] = silence_mask
        padded[-1] = False
        transitions = np.diff(padded.astype(np.int8))
        num_runs = int(np.sum(transitions == 1))
    else:
        num_runs = 0

    logger.info(f"Detected {num_runs} silence run(s) totalling {silent_duration_ms:.0f}ms "
                f"({silent_sample_count} samples)")

    if silent_sample_count > 0:
        # Generate comfort noise for the mono length
        comfort_noise = generate_comfort_noise(num_frames, noise_level_db)

        # Scale to int16 range
        comfort_noise_int16 = (comfort_noise * 32768).astype(np.int16)

        # Work in int32 to prevent overflow during addition
        samples_32 = samples_2d.astype(np.int32)

        # Inject noise into ALL channels at silent positions
        for ch in range(channels):
            samples_32[silence_mask, ch] += comfort_noise_int16[silence_mask].astype(np.int32)

        # Clip back to int16 range and flatten
        samples_out = np.clip(samples_32, -32768, 32767).astype(np.int16).flatten()

        logger.info(f"Injected comfort noise into {num_runs} run(s), {silent_duration_ms:.0f}ms total")
    else:
        samples_out = raw_samples
        logger.info("No long silence detected, skipping noise injection")

    # Convert back to AudioSegment
    modified_audio = AudioSegment(
        samples_out.tobytes(),
        frame_rate=sample_rate,
        sample_width=audio_segment.sample_width,
        channels=channels
    )

    return modified_audio
