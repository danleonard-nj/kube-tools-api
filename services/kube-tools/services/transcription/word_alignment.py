"""
Silence/energy-aware word timestamp refinement.

Redistributes word boundaries within a transcription segment using the
audio energy envelope so that pauses, hesitations, and variable speaking
rates produce more realistic timestamps than naive uniform distribution.

Design principles
-----------------
* Pure numpy — no external forced-alignment libraries.
* Deterministic — same input always produces the same output.
* Bounded complexity — O(N) in segment duration, not in vocabulary.
* Safe fallback — callers catch exceptions and revert to uniform.
"""

from typing import List, Dict, Optional

import numpy as np
from pydub import AudioSegment

from framework.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Public configuration
# ---------------------------------------------------------------------------

WORD_ALIGNMENT_MODE = "silence_aware"
"""
Controls word-timestamp strategy.

* ``"silence_aware"`` — use energy-envelope redistribution (default).
* ``"uniform"``       — character-proportional uniform distribution.
"""

# ---------------------------------------------------------------------------
# A) Energy envelope
# ---------------------------------------------------------------------------


def compute_energy_envelope_dbfs(
    samples_mono: np.ndarray,
    sample_rate: int,
    window_ms: int = 25,
) -> np.ndarray:
    """
    Per-sample dBFS using windowed RMS (cumulative-sum, O(N)).

    Matches the approach in ``_compute_windowed_dbfs`` but with a smaller
    default window (25 ms) suitable for word-boundary resolution.

    Parameters
    ----------
    samples_mono : np.ndarray
        Mono audio samples (int16 or float32).
    sample_rate : int
        Sample rate in Hz.
    window_ms : int
        RMS window in milliseconds (default 25).

    Returns
    -------
    np.ndarray
        dBFS value per sample, same length as *samples_mono*.
    """
    n = len(samples_mono)
    if n == 0:
        return np.empty(0, dtype=np.float64)

    # Normalise to float32 [-1, 1] (handles int16 and pydub-origin floats)
    samples = samples_mono.astype(np.float32)
    if np.issubdtype(samples_mono.dtype, np.integer):
        samples = samples / float(np.iinfo(samples_mono.dtype).max)
    else:
        max_abs = np.abs(samples).max()
        if max_abs > 1.0:
            samples = samples / 32768.0

    window_size = max(1, int(window_ms * sample_rate / 1000))

    squared = samples * samples
    cumsum = np.empty(n + 1, dtype=np.float64)
    cumsum[0] = 0.0
    np.cumsum(squared, out=cumsum[1:])

    half_w = window_size // 2
    idx = np.arange(n)
    left = np.clip(idx - half_w, 0, n)
    right = np.clip(idx + half_w + 1, 0, n)
    counts = (right - left).astype(np.float64)
    counts[counts == 0] = 1.0

    mean_sq = (cumsum[right] - cumsum[left]) / counts
    rms = np.sqrt(mean_sq)

    epsilon = 1e-10
    return 20.0 * np.log10(rms + epsilon)


# ---------------------------------------------------------------------------
# B) Pause mask
# ---------------------------------------------------------------------------


def detect_pause_mask(
    dbfs: np.ndarray,
    *,
    floor_pctl: float = 10,
    speech_pctl: float = 90,
    pause_gap_db: float = 8.0,
    min_pause_ms: int = 120,
    sample_rate: int,
) -> np.ndarray:
    """
    Boolean mask marking "likely pause" samples.

    Parameters
    ----------
    dbfs : np.ndarray
        Per-sample dBFS (from :func:`compute_energy_envelope_dbfs`).
    floor_pctl : float
        Percentile for noise-floor estimate (default 10).
    speech_pctl : float
        Percentile for speech-level estimate (default 90).
    pause_gap_db : float
        dB above floor to set pause threshold (default 8).
    min_pause_ms : int
        Minimum contiguous pause duration to keep (default 120 ms).
    sample_rate : int
        Audio sample rate in Hz.

    Returns
    -------
    np.ndarray[bool]
        ``True`` for samples considered to be within a pause.
    """
    n = len(dbfs)
    if n == 0:
        return np.zeros(0, dtype=bool)

    floor = float(np.percentile(dbfs, floor_pctl))
    speech = float(np.percentile(dbfs, speech_pctl))
    dynamic_range = speech - floor

    if dynamic_range < 6.0:
        # Insufficient contrast — cannot reliably distinguish pause from speech.
        return np.zeros(n, dtype=bool)

    pause_thresh = floor + pause_gap_db
    raw_mask = dbfs < pause_thresh

    # Run-length filter: keep only contiguous runs >= min_pause_samples
    min_pause_samples = max(1, int(min_pause_ms * sample_rate / 1000))

    padded = np.empty(n + 2, dtype=bool)
    padded[0] = False
    padded[1:-1] = raw_mask
    padded[-1] = False

    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)

    filtered = np.zeros(n, dtype=bool)
    for s, e in zip(starts, ends):
        if (e - s) >= min_pause_samples:
            filtered[s:e] = True

    return filtered


# ---------------------------------------------------------------------------
# C) Silence-aware word alignment
# ---------------------------------------------------------------------------

# Internal frame resolution used to keep arrays small.
_FRAME_MS = 10


def align_words_silence_aware(
    audio_segment: AudioSegment,
    segment_start_ms: int,
    segment_end_ms: int,
    words: List[str],
    *,
    window_ms: int = 25,
    min_word_ms: int = 60,
    max_word_ms: int = 1200,
    min_pause_ms: int = 120,
    pause_gap_db: float = 8.0,
    prefer_pause_gaps: bool = True,
    speaker: Optional[str] = None,
) -> List[Dict]:
    """
    Distribute word timestamps within a segment using the energy envelope.

    Instead of uniform (character-proportional) distribution, time is
    allocated proportionally to the *cumulative energy activity* so that
    high-energy (voiced) spans receive more duration and low-energy
    (pause / hesitation) spans compress or become inter-word gaps.

    Parameters
    ----------
    audio_segment : AudioSegment
        Full audio (or at least covering the segment span).
    segment_start_ms, segment_end_ms : int
        Segment boundaries in milliseconds (global timeline).
    words : list[str]
        Ordered word tokens for this segment.
    window_ms : int
        RMS window for energy envelope (default 25 ms).
    min_word_ms : int
        Floor duration per word (default 60 ms).
    max_word_ms : int
        Ceiling duration per word (default 1200 ms).
    min_pause_ms : int
        Minimum pause duration for pause-mask detection (default 120 ms).
    pause_gap_db : float
        dB above floor for pause threshold (default 8).
    prefer_pause_gaps : bool
        If ``True``, snap word boundaries to pause edges so pauses land
        *between* words rather than inside them (default ``True``).
    speaker : str or None
        Optional speaker label carried through to output dicts.

    Returns
    -------
    list[dict]
        ``[{"word": w, "start_ms": …, "end_ms": …, "speaker": …}, …]``
    """
    n_words = len(words)
    if n_words == 0:
        return []

    seg_dur_ms = segment_end_ms - segment_start_ms
    if seg_dur_ms <= 0:
        return _uniform_fallback(words, segment_start_ms, segment_end_ms, speaker)

    # --- extract mono samples for the segment span ---
    seg_audio = audio_segment[segment_start_ms:segment_end_ms]
    sample_rate = seg_audio.frame_rate
    channels = seg_audio.channels
    raw = np.array(seg_audio.get_array_of_samples(), dtype=np.int16)
    num_frames = len(raw) // channels
    if num_frames == 0:
        return _uniform_fallback(words, segment_start_ms, segment_end_ms, speaker)

    samples_2d = raw.reshape((num_frames, channels))
    samples_mono = samples_2d.mean(axis=1).astype(np.float32)

    # --- energy envelope & pause mask (sample-rate resolution) ---
    dbfs = compute_energy_envelope_dbfs(samples_mono, sample_rate, window_ms=window_ms)

    floor = float(np.percentile(dbfs, 10))
    speech = float(np.percentile(dbfs, 90))
    dynamic_range = speech - floor

    pause_mask = detect_pause_mask(
        dbfs,
        pause_gap_db=pause_gap_db,
        min_pause_ms=min_pause_ms,
        sample_rate=sample_rate,
    )

    pause_total_ms = int(np.sum(pause_mask)) * 1000.0 / sample_rate

    if dynamic_range < 6.0:
        logger.info(
            f"Word alignment fallback: dynamic_range={dynamic_range:.1f}dB < 6dB "
            f"(segment {segment_start_ms}-{segment_end_ms}ms, {n_words} words)"
        )
        return _uniform_fallback(words, segment_start_ms, segment_end_ms, speaker)

    # --- down-sample to frames for bounded computation ---
    frame_samples = max(1, int(_FRAME_MS * sample_rate / 1000))
    n_sample = len(dbfs)
    n_frames = max(1, (n_sample + frame_samples - 1) // frame_samples)

    # Per-frame mean dBFS
    padded_dbfs = np.pad(dbfs, (0, n_frames * frame_samples - n_sample), constant_values=dbfs[-1])
    frame_dbfs = padded_dbfs[:n_frames * frame_samples].reshape(n_frames, frame_samples).mean(axis=1)

    # Per-frame pause flag (majority vote per frame)
    padded_pause = np.pad(pause_mask.astype(np.float32),
                          (0, n_frames * frame_samples - n_sample),
                          constant_values=0.0)
    frame_pause = padded_pause[:n_frames * frame_samples].reshape(n_frames, frame_samples).mean(axis=1) > 0.5

    # --- activity weight: clamped normalised energy ---
    weight = np.clip((frame_dbfs - floor) / (dynamic_range + 1e-9), 0.0, 1.0)
    epsilon = 0.02  # small baseline so silent frames still accumulate *some* time
    weight = weight + epsilon

    # --- cumulative activity curve ---
    cum = np.empty(n_frames + 1, dtype=np.float64)
    cum[0] = 0.0
    np.cumsum(weight, out=cum[1:])
    c_total = cum[-1]

    if c_total <= 0:
        return _uniform_fallback(words, segment_start_ms, segment_end_ms, speaker)

    # --- choose N-1 interior boundaries evenly in C-space ---
    # boundary[k] splits word k from word k+1
    targets = np.array([cum[0] + (k + 1) * (c_total / n_words) for k in range(n_words - 1)])

    # Map each target to the nearest frame index via searchsorted
    boundary_frames = np.searchsorted(cum[1:], targets, side="left")  # 0-based frame indices
    boundary_frames = np.clip(boundary_frames, 0, n_frames - 1)

    # --- snap to pause edges if requested ---
    snapped_count = 0
    if prefer_pause_gaps and np.any(frame_pause):
        boundary_frames, snapped_count = _snap_to_pause_edges(
            boundary_frames, frame_pause, n_frames
        )

    # --- convert frame indices to ms (relative to segment start) ---
    boundaries_ms = boundary_frames.astype(np.int64) * _FRAME_MS

    # Build raw start/end pairs
    starts_ms = np.empty(n_words, dtype=np.int64)
    ends_ms = np.empty(n_words, dtype=np.int64)
    starts_ms[0] = 0
    for i in range(n_words - 1):
        ends_ms[i] = int(boundaries_ms[i])
        starts_ms[i + 1] = int(boundaries_ms[i])
    ends_ms[-1] = seg_dur_ms

    # --- enforce min/max constraints & monotonicity ---
    _enforce_constraints(starts_ms, ends_ms, n_words, seg_dur_ms, min_word_ms, max_word_ms)

    # --- build output dicts (absolute ms) ---
    result: List[Dict] = []
    for i, w in enumerate(words):
        result.append({
            "word": w,
            "start_ms": int(starts_ms[i]) + segment_start_ms,
            "end_ms": int(ends_ms[i]) + segment_start_ms,
            "speaker": speaker,
        })

    logger.info(
        f"Word alignment: segment {segment_start_ms}-{segment_end_ms}ms "
        f"({seg_dur_ms}ms), {n_words} words, "
        f"p10={floor:.1f}dB, p90={speech:.1f}dB, "
        f"dynamic_range={dynamic_range:.1f}dB, "
        f"pause_ms={pause_total_ms:.0f}, "
        f"snapped={snapped_count}"
    )

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _uniform_fallback(
    words: List[str],
    segment_start_ms: int,
    segment_end_ms: int,
    speaker: Optional[str] = None,
) -> List[Dict]:
    """
    Character-proportional uniform distribution (matches legacy behaviour).
    """
    n = len(words)
    if n == 0:
        return []

    seg_dur = segment_end_ms - segment_start_ms
    lengths = [max(len(w), 1) for w in words]
    total = sum(lengths)

    result: List[Dict] = []
    cursor = segment_start_ms
    for i, w in enumerate(words):
        ratio = lengths[i] / total
        dur = seg_dur * ratio
        end = segment_end_ms if i == n - 1 else int(cursor + dur)
        end = min(end, segment_end_ms)
        result.append({
            "word": w,
            "start_ms": int(cursor),
            "end_ms": end,
            "speaker": speaker,
        })
        cursor = end

    return result


def _snap_to_pause_edges(
    boundary_frames: np.ndarray,
    frame_pause: np.ndarray,
    n_frames: int,
) -> tuple:
    """
    If a boundary lands inside a pause run, snap it to the nearest edge.

    Returns (adjusted_boundaries, snap_count).
    """
    # Identify pause run edges
    padded = np.empty(n_frames + 2, dtype=bool)
    padded[0] = False
    padded[1:-1] = frame_pause
    padded[-1] = False
    diff = np.diff(padded.astype(np.int8))
    run_starts = np.flatnonzero(diff == 1)   # first pause frame
    run_ends = np.flatnonzero(diff == -1)    # first non-pause frame after run

    if len(run_starts) == 0:
        return boundary_frames, 0

    out = boundary_frames.copy()
    snap_count = 0

    for idx in range(len(out)):
        f = int(out[idx])
        if not frame_pause[f]:
            continue  # not inside a pause — leave it

        # Find which run this frame belongs to
        # run_starts[k] <= f < run_ends[k]
        k = int(np.searchsorted(run_starts, f, side="right")) - 1
        if k < 0 or k >= len(run_starts):
            continue
        rs, re = int(run_starts[k]), int(run_ends[k])
        if not (rs <= f < re):
            continue

        # Snap to nearest edge
        dist_left = f - rs
        dist_right = re - f
        if dist_left <= dist_right:
            out[idx] = rs  # snap to start of pause (end of previous word)
        else:
            out[idx] = re  # snap to end of pause (start of next word)

        snap_count += 1

    # Ensure sorted order after snapping
    for idx in range(1, len(out)):
        if out[idx] < out[idx - 1]:
            out[idx] = out[idx - 1]

    return out, snap_count


def _enforce_constraints(
    starts_ms: np.ndarray,
    ends_ms: np.ndarray,
    n_words: int,
    seg_dur_ms: int,
    min_word_ms: int,
    max_word_ms: int,
) -> None:
    """
    In-place enforcement of min/max duration, monotonicity, and full coverage.

    Forward pass ensures minimum durations; backward pass reclaims excess
    from words exceeding the cap; a final fixup absorbs rounding residual.
    """
    # Forward pass: enforce min_word_ms
    for i in range(n_words):
        dur = ends_ms[i] - starts_ms[i]
        if dur < min_word_ms:
            ends_ms[i] = starts_ms[i] + min_word_ms
        # Push next word start if we encroached
        if i < n_words - 1:
            if starts_ms[i + 1] < ends_ms[i]:
                starts_ms[i + 1] = ends_ms[i]

    # Backward pass: enforce max_word_ms (give surplus to next word)
    for i in range(n_words - 1, -1, -1):
        dur = ends_ms[i] - starts_ms[i]
        if dur > max_word_ms:
            excess = dur - max_word_ms
            ends_ms[i] -= excess
            if i < n_words - 1:
                starts_ms[i + 1] = ends_ms[i]

    # Clamp everything to segment bounds
    for i in range(n_words):
        starts_ms[i] = max(0, min(starts_ms[i], seg_dur_ms))
        ends_ms[i] = max(starts_ms[i], min(ends_ms[i], seg_dur_ms))

    # Monotonicity fixup (forward propagation of minimal spacing)
    for i in range(1, n_words):
        if starts_ms[i] < ends_ms[i - 1]:
            starts_ms[i] = ends_ms[i - 1]
        if ends_ms[i] < starts_ms[i]:
            ends_ms[i] = starts_ms[i]

    # Final word must reach segment end — absorb residual
    ends_ms[-1] = seg_dur_ms
    # First word must start at segment start
    starts_ms[0] = 0
