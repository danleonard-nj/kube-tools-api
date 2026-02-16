"""DSP helpers: silence detection, comfort-noise injection, MIME types, size checks."""

import io
import threading
import time
from typing import Tuple

import numpy as np
from pydub import AudioSegment

from framework.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional Numba acceleration for IIR high-pass filter
# Falls back to pure-Python loops when numba is not installed.
# ---------------------------------------------------------------------------
try:
    from numba import njit as _njit
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False


def _hp_2pole_iir_py(noise, alpha):
    """Two-pole IIR high-pass filter (pure-Python fallback)."""
    n = len(noise)
    filtered = np.empty(n, dtype=np.float32)
    prev_x = np.float32(0.0)
    prev_y = np.float32(0.0)
    for i in range(n):
        filtered[i] = alpha * (prev_y + noise[i] - prev_x)
        prev_x = noise[i]
        prev_y = filtered[i]
    out = np.empty(n, dtype=np.float32)
    prev_x = np.float32(0.0)
    prev_y = np.float32(0.0)
    for i in range(n):
        out[i] = alpha * (prev_y + filtered[i] - prev_x)
        prev_x = filtered[i]
        prev_y = out[i]
    return out


if _HAS_NUMBA:
    _hp_2pole_iir = _njit(cache=True, fastmath=True)(_hp_2pole_iir_py)
    # Warmup: trigger JIT compilation on a tiny input so the first real
    # request doesn't pay the ~1-2 s compile cost.
    _hp_2pole_iir(np.zeros(16, dtype=np.float32), np.float32(0.5))
    logger.info("Numba JIT compiled _hp_2pole_iir (IIR high-pass filter)")
else:
    _hp_2pole_iir = _hp_2pole_iir_py
    logger.info("Numba not available \u2014 using pure-Python IIR high-pass filter")

# ---------------------------------------------------------------------------
# Cached high-pass filtered noise buffer
# ---------------------------------------------------------------------------
_NOISE_CACHE_SECONDS = 90
_noise_cache: dict = {}
_noise_cache_lock = threading.Lock()


def _get_cached_filtered_noise(
    sample_rate: int,
    cutoff_hz: float,
) -> np.ndarray:
    """Return a long pre-filtered noise buffer, creating it on first call.

    The buffer is ~90 s of white noise high-pass filtered at *cutoff_hz*.
    Callers slice random windows out of it and apply per-run jitter and
    amplitude scaling, so the result is never a recognisable repeating
    pattern.  Memory cost: ~17 MB per unique (sample_rate, cutoff_hz) pair.
    """
    key = (sample_rate, cutoff_hz)
    cached = _noise_cache.get(key)
    if cached is not None:
        return cached

    with _noise_cache_lock:
        # Double-check after acquiring lock
        cached = _noise_cache.get(key)
        if cached is not None:
            return cached

        num_samples = int(_NOISE_CACHE_SECONDS * sample_rate)
        noise = np.random.randn(num_samples).astype(np.float32)
        max_abs = np.abs(noise).max()
        if max_abs > 0:
            noise /= max_abs

        omega_c = 2.0 * np.pi * cutoff_hz
        dt = 1.0 / sample_rate
        rc = 1.0 / omega_c
        alpha = np.float32(dt / (rc + dt))

        noise = _hp_2pole_iir(noise, alpha)

        max_abs = np.abs(noise).max()
        if max_abs > 0:
            noise /= max_abs

        _noise_cache[key] = noise
        logger.info(
            f"Created noise cache: {_NOISE_CACHE_SECONDS}s at {sample_rate}Hz, "
            f"cutoff={cutoff_hz}Hz, {noise.nbytes / 1024:.0f}KB"
        )
        return noise


def _find_mask_runs(mask: np.ndarray):
    """Return list of (start, end) index pairs for contiguous True runs."""
    n = len(mask)
    if n == 0:
        return []
    padded = np.empty(n + 2, dtype=bool)
    padded[0] = False
    padded[1:-1] = mask
    padded[-1] = False
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)
    return list(zip(starts.tolist(), ends.tolist()))


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


def generate_comfort_noise(
    num_samples: int,
    sample_rate: int,
    amplitude_db: float = -60,
    highpass_cutoff_hz: float = 5000,
    jitter_period_samples: int = 1024
) -> np.ndarray:
    """
    Generate high-pass filtered comfort noise with temporal jitter.

    This noise keeps the ASR encoder active but is NOT decodable as speech:
    - High-pass filtered above 5 kHz (well above speech formants ~100-3000 Hz)
    - Time-varying amplitude with random jitter to prevent pattern recognition
    - Very low level (-60 dB) to remain imperceptible

    Args:
        num_samples: Number of samples to generate
        sample_rate: Audio sample rate in Hz (needed for filtering)
        amplitude_db: Base amplitude in dB relative to full scale (default -60 dB)
        highpass_cutoff_hz: High-pass cutoff frequency (default 5000 Hz)
        jitter_period_samples: Period for amplitude jitter (default 1024 samples)

    Returns:
        numpy array of filtered, jittered noise samples (float32, range -1 to 1)
    """
    # Generate white noise
    noise = np.random.randn(num_samples).astype(np.float32)

    # Normalize to [-1, 1] range
    max_abs = np.abs(noise).max()
    if max_abs > 0:
        noise = noise / max_abs

    # --- High-pass filter: two-pole IIR (cascaded first-order stages) ---
    # Two poles give -12 dB/octave rolloff (vs -6 dB/octave for single pole),
    # keeping significantly more energy out of the speech formant range
    # (100-3000 Hz) so the noise cannot be decoded as phonemes.
    omega_c = 2.0 * np.pi * highpass_cutoff_hz
    dt = 1.0 / sample_rate
    rc = 1.0 / omega_c
    alpha = np.float32(dt / (rc + dt))

    # Numba-accelerated when available, pure-Python fallback otherwise
    noise = _hp_2pole_iir(noise, alpha)

    # Normalize again after filtering
    max_abs = np.abs(noise).max()
    if max_abs > 0:
        noise = noise / max_abs

    # --- Temporal amplitude jitter (prevents steady-state pattern detection) ---
    # Create random amplitude envelope that varies smoothly
    num_jitter_blocks = max(1, num_samples // jitter_period_samples + 1)
    # Random multipliers in range [0.5, 1.5] for ±3dB variation
    jitter_envelope = 0.5 + np.random.rand(num_jitter_blocks).astype(np.float32)
    # Repeat each value for jitter_period_samples and trim to exact length
    jitter_repeated = np.repeat(jitter_envelope, jitter_period_samples)[:num_samples]
    noise = noise * jitter_repeated

    # Apply base amplitude adjustment
    amplitude = 10 ** (amplitude_db / 20)
    noise = noise * amplitude

    return noise


def _compute_windowed_dbfs(
    samples: np.ndarray,
    sample_rate: int,
    window_ms: int = 100
) -> np.ndarray:
    """
    Compute per-sample dBFS using windowed RMS (O(N) cumulative-sum method).

    Always normalizes to absolute full-scale: integer samples are divided by
    their dtype max, float samples by 32768 (pydub int16 origin).

    Args:
        samples: Mono audio samples (any numeric dtype)
        sample_rate: Sample rate in Hz
        window_ms: RMS window size in ms (default 100)

    Returns:
        numpy array of dBFS values per sample
    """
    n = len(samples)

    # --- Normalise to float32 in [-1, 1] relative to FULL SCALE ---
    # pydub always produces int16 (-32768..32767).  When the caller does
    #   samples_mono = samples_2d.mean(axis=1).astype(np.float32)
    # the values are still in the int16 *range* but typed as float32.
    # We must divide by 32768 (not by max_abs) so that dBFS values are
    # absolute, independent of how loud the recording happens to be.
    if np.issubdtype(samples.dtype, np.integer):
        samples = samples.astype(np.float32) / float(np.iinfo(samples.dtype).max)
    else:
        samples = samples.astype(np.float32)
        # Detect pydub-origin floats still in int16 range
        max_abs = np.abs(samples).max()
        if max_abs > 1.0:
            samples = samples / 32768.0

    # Guard window_size >= 1
    window_size = max(1, int(window_ms * sample_rate / 1000))

    # --- Windowed RMS via cumulative sum (O(N), no convolve) ---
    squared = samples * samples
    cumsum = np.empty(n + 1, dtype=np.float64)
    cumsum[0] = 0.0
    np.cumsum(squared, out=cumsum[1:])

    half_w = window_size // 2
    idx = np.arange(n)
    left = np.clip(idx - half_w, 0, n)
    right = np.clip(idx + half_w + 1, 0, n)   # symmetric window
    counts = (right - left).astype(np.float64)
    counts[counts == 0] = 1.0

    mean_sq = (cumsum[right] - cumsum[left]) / counts
    rms = np.sqrt(mean_sq)

    # --- Convert to dBFS safely ---
    epsilon = 1e-10
    return 20.0 * np.log10(rms + epsilon)


def detect_long_silences(
    samples: np.ndarray,
    sample_rate: int,
    silence_thresh_dbfs: float = -42,
    min_silence_ms: int = 1500,
    window_ms: int = 100,
    true_silence_dbfs: float = -55,
    adaptive_fallback: bool = True,
    adaptive_coarse_gap_db: float = 18.0,
    adaptive_fine_gap_db: float = 10.0
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect long silence regions with two-tier gating for selective noise injection.

    Returns TWO masks:
    1. coarse_silence: Silence regions for initial detection
    2. true_silence: Low-energy regions for noise injection (subset of coarse)

    **Adaptive thresholding (default enabled):**
    Fixed absolute thresholds (-42/-55 dBFS) only work for audio recorded at
    "standard" gain levels. They fail on:
    - Browser/WebRTC recordings (AGC keeps "silence" at -25 to -35 dBFS)
    - Quiet phone recordings (speech at -40 dBFS, silence at -60 dBFS)
    - Loud recordings (speech at -10 dBFS, everything below -42 is "silence")

    The function automatically validates fixed thresholds against the audio's
    dynamic range and switches to adaptive mode when:
    - Dynamic range < 10 dB (can't distinguish speech from silence)
    - Fixed coarse threshold < 12 dB below speech peak (would catch speech)
    - Fixed coarse threshold > median dBFS (would mark >50% as silence)
    - Fixed thresholds mark >60% of audio as silence (sanity check)

    Adaptive mode computes thresholds relative to the audio's own levels:
        speech_level  = 90th percentile of per-frame dBFS
        floor_level   = 10th percentile of per-frame dBFS
        coarse_thresh = floor + adaptive_coarse_gap_db (default +18 dB)
        fine_thresh   = floor + adaptive_fine_gap_db (default +10 dB)

    Both are clamped to stay at least 12 dB below speech level for safety.

    This works regardless of recording level because it keys off the
    *contrast* between speech and silence, not absolute energy.

    Args:
        samples: Audio samples as numpy array (mono, any numeric dtype)
        sample_rate: Sample rate in Hz
        silence_thresh_dbfs: Fixed coarse threshold (default -42)
        min_silence_ms: Minimum silence duration to detect (default 1500ms)
        window_ms: Window size for RMS computation (default 100ms)
        true_silence_dbfs: Fixed fine threshold for injection (default -55)
        adaptive_fallback: If True, validate and override fixed thresholds (default True)
        adaptive_coarse_gap_db: dB above floor for adaptive coarse gate (default 18)
        adaptive_fine_gap_db: dB above floor for adaptive fine gate (default 10)

    Returns:
        Tuple of (coarse_silence_mask, true_silence_mask)
    """
    n = len(samples)
    if n == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)

    dbfs = _compute_windowed_dbfs(samples, sample_rate, window_ms)

    # Compute dynamic range for adaptive thresholding
    _p10, _p50, _p90 = np.percentile(dbfs, [10, 50, 90])
    p10, p50, p90 = float(_p10), float(_p50), float(_p90)
    dynamic_range = p90 - p10

    logger.info(f"Audio dBFS distribution: p10={p10:.1f}, p50={p50:.1f}, p90={p90:.1f}, "
                f"range={dynamic_range:.1f}dB "
                f"(fixed coarse={silence_thresh_dbfs}, fixed fine={true_silence_dbfs})")

    min_samples = max(1, int(min_silence_ms * sample_rate / 1000))

    def _apply_gates(coarse_thresh: float, fine_thresh: float) -> Tuple[np.ndarray, np.ndarray]:
        """Apply two-tier gating with run-length filtering."""
        coarse_mask = dbfs < coarse_thresh
        fine_mask = dbfs < fine_thresh

        # Run-length filter: keep only silence runs >= min_samples
        padded = np.empty(n + 2, dtype=bool)
        padded[0] = False
        padded[1:-1] = coarse_mask
        padded[-1] = False

        diff = np.diff(padded.astype(np.int8))
        starts = np.flatnonzero(diff == 1)
        ends = np.flatnonzero(diff == -1)

        filtered_coarse = np.zeros(n, dtype=bool)
        for s, e in zip(starts, ends):
            if (e - s) >= min_samples:
                filtered_coarse[s:e] = True

        # Fine mask is intersection: in a long silence region AND below fine threshold
        filtered_fine = filtered_coarse & fine_mask
        return filtered_coarse, filtered_fine

    # --- Validate if fixed thresholds make sense for this audio ---
    # Fixed thresholds work when:
    # 1. Audio has sufficient dynamic range (>= 10 dB)
    # 2. Fixed coarse threshold is reasonably below speech level (>= 12 dB gap)
    # 3. Fixed coarse threshold doesn't catch more than 50% of audio
    #
    # Otherwise, the fixed thresholds are mismatched to the recording level.
    use_adaptive = False

    if adaptive_fallback:
        if dynamic_range < 10.0:
            logger.info(f"Adaptive mode: insufficient dynamic range ({dynamic_range:.1f}dB < 10dB)")
            use_adaptive = True
        elif (silence_thresh_dbfs - p90) > -12.0:
            # Coarse threshold is less than 12 dB below speech level
            gap = p90 - silence_thresh_dbfs
            logger.info(f"Adaptive mode: fixed coarse threshold too close to speech "
                        f"(only {gap:.1f}dB below p90={p90:.1f}dB, need >= 12dB)")
            use_adaptive = True
        elif p50 < silence_thresh_dbfs:
            # Median is below coarse threshold = more than half the audio is "silence"
            logger.info(f"Adaptive mode: fixed coarse threshold too high "
                        f"(p50={p50:.1f}dB < coarse={silence_thresh_dbfs}dB, would mark >50% as silence)")
            use_adaptive = True

    if not use_adaptive:
        # Fixed thresholds look reasonable, try them
        filtered_coarse_mask, final_fine_mask = _apply_gates(silence_thresh_dbfs, true_silence_dbfs)

        # Sanity check: if we detected more than 60% of audio as silence, something is wrong
        coarse_count = int(np.sum(filtered_coarse_mask))
        if coarse_count > 0:
            silence_fraction = coarse_count / n
            if silence_fraction > 0.60:
                logger.warning(f"Fixed thresholds marked {silence_fraction*100:.0f}% of audio as silence "
                               f"(suspiciously high), switching to adaptive")
                use_adaptive = True
            else:
                logger.info(f"Fixed thresholds: {silence_fraction*100:.0f}% of audio marked as silence (reasonable)")
                return filtered_coarse_mask, final_fine_mask
        else:
            # No silence detected with fixed thresholds
            logger.info("Fixed thresholds detected no silence, trying adaptive")
            use_adaptive = True

    # --- Adaptive thresholding ---
    # This happens with browser audio (WebRTC AGC, comfort noise, noise gates)
    # or recordings at unusual gain levels where "silence" doesn't match
    # our fixed -42/-55 dBFS expectations.
    #
    # Strategy: use the audio's own floor level as reference.
    # p10 approximates the noise floor, p90 approximates speech level.
    if dynamic_range < 6.0:
        # Less than 6 dB dynamic range = probably constant noise or silence,
        # nothing meaningful to gate
        logger.warning(f"Adaptive mode: dynamic range only {dynamic_range:.1f}dB, "
                       f"insufficient to distinguish speech from silence")
        return np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)

    adaptive_coarse = p10 + adaptive_coarse_gap_db
    adaptive_fine = p10 + adaptive_fine_gap_db

    # Safety: adaptive coarse must stay below speech level to avoid
    # injecting noise over speech
    speech_guard = p90 - 12.0  # at least 12 dB below speech peak
    if adaptive_coarse > speech_guard:
        logger.info(f"Adaptive coarse {adaptive_coarse:.1f}dB clamped to {speech_guard:.1f}dB "
                    f"(12dB below speech peak)")
        adaptive_coarse = speech_guard

    adaptive_fine = min(adaptive_fine, adaptive_coarse - 3.0)  # at least 3 dB separation

    logger.info(f"Adaptive thresholds: floor={p10:.1f}dB, speech={p90:.1f}dB, "
                f"dynamic_range={dynamic_range:.1f}dB → "
                f"coarse={adaptive_coarse:.1f}dB, fine={adaptive_fine:.1f}dB")

    filtered_coarse_mask, final_fine_mask = _apply_gates(adaptive_coarse, adaptive_fine)

    adaptive_coarse_ms = int(np.sum(filtered_coarse_mask)) * 1000.0 / sample_rate
    adaptive_fine_ms = int(np.sum(final_fine_mask)) * 1000.0 / sample_rate
    adaptive_silence_fraction = int(np.sum(filtered_coarse_mask)) / n if n > 0 else 0

    logger.info(f"Adaptive detection: {adaptive_coarse_ms:.0f}ms coarse silence "
                f"({adaptive_silence_fraction*100:.0f}% of audio), "
                f"{adaptive_fine_ms:.0f}ms fine silence")

    return filtered_coarse_mask, final_fine_mask


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


def is_single_shot_safe(audio_segment: AudioSegment, max_size_mb: float = 22.0, source_format: str = '') -> Tuple[bool, str]:
    """
    Determine if audio can be safely transcribed in a single shot.

    Performs an actual export to BytesIO and checks the real byte length.
    The estimate function is used as a fast pre-check, but the real export is
    the final gate.  Default 22 MB leaves headroom for multipart container
    wrapping and metadata below the 25 MB API limit.

    WebM files (typically Opus codec from browsers) use WAV export for better
    compatibility, as FLAC export from Opus can fail or produce corrupt files.

    Args:
        audio_segment: Audio to check
        max_size_mb: Maximum safe size in MB (default 22.0 to leave margin below 25MB)
        source_format: Original file extension (used to detect WebM/Opus files)

    Returns:
        Tuple of (is_safe, format_to_use)
        - is_safe: True if single-shot is safe
        - format_to_use: 'flac' or 'wav'
    """
    # WebM files (Opus codec) should use WAV for reliable export
    # FLAC export from Opus often produces 0-byte or corrupt files
    export_format = 'wav' if source_format.lower() == 'webm' else 'flac'

    # Fast estimate pre-check — skip expensive export when clearly safe/unsafe
    estimated_mb = estimate_encoded_size_mb(audio_segment, export_format)
    if estimated_mb > max_size_mb * 1.5:
        logger.info(f"Estimated {export_format.upper()} size {estimated_mb:.1f}MB far exceeds {max_size_mb}MB, skipping export check")
        return False, export_format

    # Real-size gate: actually export and measure
    buf = io.BytesIO()
    try:
        audio_segment.export(buf, format=export_format)
        actual_bytes = buf.tell()  # Size without copying buffer contents
        actual_mb = actual_bytes / (1024 * 1024)

        # Sanity check: if export produced a suspiciously small file, it likely failed
        if actual_mb < 0.001 and len(audio_segment) > 100:  # Less than 1KB for audio > 100ms is suspicious
            logger.warning(f"{export_format.upper()} export produced only {actual_bytes} bytes for {len(audio_segment)}ms audio, trying WAV fallback")
            if export_format == 'flac':
                # Retry with WAV
                buf = io.BytesIO()
                audio_segment.export(buf, format='wav')
                actual_bytes = buf.tell()
                actual_mb = actual_bytes / (1024 * 1024)
                export_format = 'wav'
                logger.info(f"WAV fallback produced {actual_mb:.2f}MB")
    except Exception as e:
        logger.error(f"Failed to export as {export_format.upper()}: {e}, trying WAV fallback")
        buf = io.BytesIO()
        audio_segment.export(buf, format='wav')
        actual_bytes = buf.tell()
        actual_mb = actual_bytes / (1024 * 1024)
        export_format = 'wav'

    logger.info(f"Actual {export_format.upper()} size: {actual_mb:.2f}MB (estimate was {estimated_mb:.1f}MB, limit {max_size_mb}MB)")

    if actual_mb < max_size_mb:
        return True, export_format

    logger.info(f"Actual {export_format.upper()} size {actual_mb:.2f}MB >= {max_size_mb}MB, will use chunking")
    return False, export_format


def _shape_injection_mask(
    coarse_mask: np.ndarray,
    fine_mask: np.ndarray,
    sample_rate: int,
    grace_ms: int = 150,
    tail_ms: int = 100
) -> np.ndarray:
    """
    Apply temporal hysteresis to produce a shaped injection mask.

    Shaping operates on the **coarse** mask (contiguous runs from
    run-length filtering) to determine *where* grace/tail zones go,
    then intersects the shaped zone with the **fine** mask to decide
    *which samples* actually receive noise.

    This two-step approach is critical because the fine mask is often
    fragmented within a single silence region (momentary codec artifacts,
    ambient micro-spikes, etc.).  Shaping the fine mask directly would
    break one 3-second silence into dozens of sub-runs each < grace+tail,
    resulting in zero injection.

    Each coarse silence run is carved into three temporal zones:

        speech
         → [grace_ms] natural silence preserved   (no injection)
         → [interior] stabilization noise active   (injection where fine=True)
         → [tail_ms]  clean silence buffer         (no injection)
         → speech

    Preserves:
    - Natural sentence-ending pauses (punctuation inference)
    - Speaker handoff cues (diarization)
    - Clean speech-onset transitions

    Coarse runs shorter than (grace_ms + tail_ms) receive NO injection —
    the silence is short enough that the encoder will survive.

    Args:
        coarse_mask: Boolean per-sample mask (contiguous runs, from coarse gate)
        fine_mask: Boolean per-sample mask (may be fragmented, from fine gate)
        sample_rate: Audio sample rate in Hz
        grace_ms: Natural silence to preserve at start of each run (default 400)
        tail_ms: Clean silence buffer at end of each run (default 300)

    Returns:
        Shaped boolean mask — injection targets within grace/tail boundaries
    """
    n = len(coarse_mask)
    if n == 0:
        return coarse_mask.copy()

    grace_samples = max(1, int(grace_ms * sample_rate / 1000))
    tail_samples = max(1, int(tail_ms * sample_rate / 1000))

    # Find contiguous runs from the COARSE mask (guaranteed contiguous
    # from run-length filtering in detect_long_silences)
    padded = np.empty(n + 2, dtype=bool)
    padded[0] = False
    padded[1:-1] = coarse_mask
    padded[-1] = False
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)

    # Build the eligible injection zone from coarse runs
    eligible = np.zeros(n, dtype=bool)
    shaped_runs = 0
    skipped_short = 0

    for s, e in zip(starts, ends):
        run_len = e - s
        min_injectable = grace_samples + tail_samples

        if run_len <= min_injectable:
            # Too short for grace + tail — encoder survives this, skip
            skipped_short += 1
            continue

        # Carve out: [s .. s+grace) = natural silence
        #            [s+grace .. e-tail) = eligible zone
        #            [e-tail .. e) = clean buffer
        inject_start = s + grace_samples
        inject_end = e - tail_samples
        eligible[inject_start:inject_end] = True
        shaped_runs += 1

    # Intersect eligible zone with fine mask for actual injection targets.
    # This ensures we only inject where the audio is actually quiet enough,
    # while the shaping (grace/tail) is based on stable coarse boundaries.
    shaped = eligible & fine_mask

    # If the fine mask is so fragmented that the intersection is empty
    # but we have eligible coarse zones, inject into the eligible zone
    # directly — the coarse gate already confirmed these are silence regions
    # and the encoder needs stimulation.
    if shaped_runs > 0 and int(np.sum(shaped)) == 0:
        eligible_ms = int(np.sum(eligible)) * 1000.0 / sample_rate
        logger.warning(f"Fine mask fragmentation eliminated all injection targets "
                       f"({eligible_ms:.0f}ms eligible). Falling back to coarse-only injection.")
        shaped = eligible

    logger.info(f"Injection shaping: {len(starts)} coarse runs → "
                f"{shaped_runs} with injection zones ({skipped_short} too short, "
                f"grace={grace_ms}ms, tail={tail_ms}ms)")

    return shaped


def inject_comfort_noise(
    audio_segment: AudioSegment,
    noise_level_db: float = -60,
    silence_thresh_dbfs: float = -42,
    min_silence_ms: int = 1500,
    true_silence_dbfs: float = -55,
    grace_ms: int = 400,
    tail_ms: int = 300
) -> AudioSegment:
    """
    Inject stabilization noise into sustained silence with temporal hysteresis.

    Rather than injecting noise immediately when silence is detected, each
    silence region is carved into three temporal zones:

        speech
         → [grace_ms]  natural silence preserved   (no injection)
         → [interior]  stabilization noise active   (injection)
         → [tail_ms]   clean silence buffer         (no injection)
         → speech

    This preserves natural pauses for punctuation inference and diarization
    while still preventing encoder state collapse in sustained zero-energy
    spans.

    Detection uses two-tier RMS/energy gating with adaptive thresholds:
    1. Coarse gate: Detects long silent regions (>= min_silence_ms)
    2. Fine gate: Within those regions, identifies quiet spans for injection
    3. Shaping: Applies grace period + tail buffer to each injection zone

    Noise characteristics designed to minimize linguistic decodability:
    - High-pass filtered above 5 kHz with 2-pole (-12 dB/oct) rolloff
    - Temporally jittered amplitude (prevents pattern recognition)
    - Very low level (-60 dB, imperceptible)

    Handles any channel count: silence detection uses mono mixdown, noise is
    injected into all channels. Arithmetic is done in int32 and clipped to int16.

    Args:
        audio_segment: The audio to process
        noise_level_db: Noise amplitude in dB (default -60, very quiet)
        silence_thresh_dbfs: Coarse threshold for silence detection (default -42)
        min_silence_ms: Minimum silence duration to consider (default 1500ms)
        true_silence_dbfs: Threshold for noise injection (default -55)
        grace_ms: Natural silence to preserve before injection (default 400)
        tail_ms: Clean silence buffer after injection (default 300)

    Returns:
        Modified AudioSegment with temporally-shaped stabilization noise
    """
    t0 = time.perf_counter()
    sample_rate = audio_segment.frame_rate
    channels = audio_segment.channels

    logger.info(f"Comfort noise injection: coarse={silence_thresh_dbfs}dBFS, "
                f"fine={true_silence_dbfs}dBFS, min_duration={min_silence_ms}ms, "
                f"grace={grace_ms}ms, tail={tail_ms}ms")

    # Convert to numpy array (int16)
    t_convert = time.perf_counter()
    raw_samples = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)
    num_frames = len(raw_samples) // channels
    samples_2d = raw_samples.reshape((num_frames, channels))
    logger.info(f"[timing] stage=inject_comfort_noise.to_numpy duration_ms={int((time.perf_counter() - t_convert) * 1000)} frames={num_frames} ch={channels}")

    # Mono mixdown for silence detection
    t_mix = time.perf_counter()
    samples_mono = samples_2d.mean(axis=1).astype(np.float32)
    logger.info(f"[timing] stage=inject_comfort_noise.mixdown duration_ms={int((time.perf_counter() - t_mix) * 1000)}")

    # Two-tier gating with adaptive thresholds
    t_detect = time.perf_counter()
    coarse_silence_mask, fine_silence_mask = detect_long_silences(
        samples_mono,
        sample_rate,
        silence_thresh_dbfs=silence_thresh_dbfs,
        min_silence_ms=min_silence_ms,
        true_silence_dbfs=true_silence_dbfs
    )
    logger.info(f"[timing] stage=inject_comfort_noise.detect_silence duration_ms={int((time.perf_counter() - t_detect) * 1000)}")

    coarse_count = int(np.sum(coarse_silence_mask))
    fine_count = int(np.sum(fine_silence_mask))
    coarse_duration_ms = coarse_count * 1000.0 / sample_rate
    fine_duration_ms = fine_count * 1000.0 / sample_rate

    logger.info(f"Detected {coarse_duration_ms:.0f}ms coarse silence, "
                f"{fine_duration_ms:.0f}ms fine silence")

    if fine_count == 0:
        logger.warning("No silence detected even with adaptive fallback — "
                       "audio may have insufficient dynamic range for noise injection")
        return audio_segment

    # Apply temporal hysteresis: grace period + tail buffer
    # Shape against COARSE mask (contiguous runs), intersect with fine mask
    # for injection targets.  Shaping the fine mask directly fails because
    # it fragments into tiny sub-runs that all fall below grace+tail.
    t_shape = time.perf_counter()
    injection_mask = _shape_injection_mask(
        coarse_silence_mask,
        fine_silence_mask,
        sample_rate,
        grace_ms=grace_ms,
        tail_ms=tail_ms
    )
    logger.info(f"[timing] stage=inject_comfort_noise.shape_mask duration_ms={int((time.perf_counter() - t_shape) * 1000)}")

    injection_count = int(np.sum(injection_mask))
    injection_duration_ms = injection_count * 1000.0 / sample_rate

    if injection_count == 0:
        logger.info(f"All {fine_count * 1000.0 / sample_rate:.0f}ms of silence "
                    f"falls within grace/tail margins — no injection needed "
                    f"(silence runs too short to threaten encoder stability)")
        return audio_segment

    # Find contiguous injection runs (used for both logging and run-based injection)
    injection_runs = _find_mask_runs(injection_mask)
    num_injection_runs = len(injection_runs)

    logger.info(f"Will inject noise into {num_injection_runs} region(s), "
                f"{injection_duration_ms:.0f}ms total "
                f"(from {fine_duration_ms:.0f}ms fine silence, "
                f"after {grace_ms}ms grace + {tail_ms}ms tail shaping)")

    # Get (or create) cached high-pass filtered noise buffer.
    # The buffer is generated and filtered once per (sample_rate, cutoff_hz)
    # pair; subsequent calls just slice into it.
    t_gen = time.perf_counter()
    cached_noise = _get_cached_filtered_noise(sample_rate, 5000)
    cache_len = len(cached_noise)
    amplitude = np.float32(10 ** (noise_level_db / 20))
    logger.info(f"[timing] stage=inject_comfort_noise.generate_noise duration_ms={int((time.perf_counter() - t_gen) * 1000)}")

    # Work in int32 to prevent overflow during addition
    samples_32 = samples_2d.astype(np.int32)

    # Inject noise per-run: slice from cache, apply jitter + amplitude, add.
    # Each run gets a random offset into the cache so the noise varies.
    t_inject = time.perf_counter()
    jitter_period = 1024
    for run_start, run_end in injection_runs:
        run_len = run_end - run_start

        # Pick a random offset into the cached buffer for variety
        if run_len <= cache_len:
            max_offset = max(1, cache_len - run_len)
            offset = np.random.randint(0, max_offset)
            noise_slice = cached_noise[offset:offset + run_len].copy()
        else:
            # Very long run (>90 s): tile from cache with varying offsets
            pieces = []
            remaining = run_len
            while remaining > 0:
                chunk = min(remaining, cache_len)
                off = np.random.randint(0, max(1, cache_len - chunk))
                pieces.append(cached_noise[off:off + chunk])
                remaining -= chunk
            noise_slice = np.concatenate(pieces)

        # Per-run jitter envelope (\u00b13 dB variation)
        num_blocks = max(1, run_len // jitter_period + 1)
        jitter = np.float32(0.5) + np.random.rand(num_blocks).astype(np.float32)
        jitter_env = np.repeat(jitter, jitter_period)[:run_len]

        # Scale: jitter * base amplitude \u2192 int32 for safe mixing
        noise_int32 = (noise_slice * jitter_env * amplitude * np.float32(32768.0)).astype(np.int32)
        for ch in range(channels):
            samples_32[run_start:run_end, ch] += noise_int32

    logger.info(f"[timing] stage=inject_comfort_noise.apply_injection duration_ms={int((time.perf_counter() - t_inject) * 1000)}")

    # Clip back to int16 range and flatten
    samples_out = np.clip(samples_32, -32768, 32767).astype(np.int16).flatten()

    logger.info(f"Injected stabilization noise into {num_injection_runs} region(s), "
                f"{injection_duration_ms:.0f}ms total")

    # Convert back to AudioSegment
    t_segment = time.perf_counter()
    modified_audio = AudioSegment(
        samples_out.tobytes(),
        frame_rate=sample_rate,
        sample_width=audio_segment.sample_width,
        channels=channels
    )
    logger.info(f"[timing] stage=inject_comfort_noise.to_audiosegment duration_ms={int((time.perf_counter() - t_segment) * 1000)}")

    logger.info(
        f"[timing] stage=inject_comfort_noise.total duration_ms={int((time.perf_counter() - t0) * 1000)} "
        f"audio_ms={len(audio_segment)} sr={sample_rate} ch={channels}"
    )

    return modified_audio
