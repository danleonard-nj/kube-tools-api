"""Silence detection, mask shaping, and gap-merging utilities.

Provides VAD-based silence detection (primary), RMS-based detection
(fallback for non-pipeline uses like word alignment), contiguous-run
helpers, and mask shaping for the excision pipeline.
"""

import time
from math import gcd, log1p

import numpy as np
import webrtcvad
from scipy.signal import resample_poly

from framework.logger import get_logger
from services.transcription.dsp.debug import DEBUG_DSP

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Contiguous-run helper
# ---------------------------------------------------------------------------

def _find_mask_runs(mask: np.ndarray) -> list[tuple[int, int]]:
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


# ---------------------------------------------------------------------------
# Gap merging helper
# ---------------------------------------------------------------------------

def _merge_short_gaps(
    silence_mask: np.ndarray,
    sample_rate: int,
    min_gap_ms: int = 150,
) -> tuple[np.ndarray, int]:
    """Merge silence regions separated by gaps shorter than *min_gap_ms*.

    Finds contiguous speech (non-silence) runs between silence regions.
    Any speech run shorter than *min_gap_ms* is reclassified as silence,
    bridging the two surrounding silence regions into one.

    Returns the updated mask and the number of gaps merged.
    """
    min_gap_samples = max(1, int(min_gap_ms * sample_rate / 1000))
    speech_runs = _find_mask_runs(~silence_mask)
    merged = silence_mask.copy()
    n_merged = 0
    for start, end in speech_runs:
        run_len = end - start
        if run_len < min_gap_samples:
            # Only merge if bordered by silence on both sides
            has_sil_before = (start == 0) or silence_mask[start - 1]
            has_sil_after = (end >= len(silence_mask)) or silence_mask[min(end, len(silence_mask) - 1)]
            if has_sil_before and has_sil_after:
                merged[start:end] = True
                n_merged += 1
    return merged, n_merged


# ---------------------------------------------------------------------------
# WebRTC VAD-based silence detection
# ---------------------------------------------------------------------------

def _detect_silence_vad(
    samples_mono: np.ndarray,
    sample_rate: int,
    aggressiveness: int = 3,
    frame_ms: int = 20,
    min_silence_ms: int = 1500,
    min_gap_ms: int = 400,
) -> np.ndarray:
    """Detect silence using WebRTC VAD with gap merging.

    WebRTC VAD classifies frames by spectral characteristics, not just
    energy — so transient spikes (mic bumps, taps) that exceed RMS
    thresholds are still correctly labelled as non-speech.

    Returns a boolean mask where True = silence (same semantics as
    the coarse mask from ``detect_long_silences``).
    """
    t_start = time.perf_counter()
    n_orig = len(samples_mono)

    # -- Resample to a VAD-compatible rate if needed ----------------------
    vad_rates = {8000, 16000, 32000, 48000}
    if sample_rate in vad_rates:
        vad_sr = sample_rate
        vad_samples = samples_mono
    else:
        vad_sr = 16000
        g = gcd(sample_rate, vad_sr)
        vad_samples = resample_poly(
            samples_mono, up=vad_sr // g, down=sample_rate // g,
        ).astype(np.float32)

    # -- Convert float32 → int16 bytes for VAD ----------------------------
    pcm_i16 = np.clip(vad_samples * 32767.0, -32768, 32767).astype(np.int16)
    frame_samples = int(vad_sr * frame_ms / 1000)
    frame_bytes = frame_samples * 2  # int16 = 2 bytes/sample
    n_frames = len(pcm_i16) // frame_samples

    vad = webrtcvad.Vad(aggressiveness)
    is_speech = np.zeros(n_frames, dtype=bool)
    for i in range(n_frames):
        offset = i * frame_samples
        chunk = pcm_i16[offset:offset + frame_samples].tobytes()
        if len(chunk) == frame_bytes:
            is_speech[i] = vad.is_speech(chunk, vad_sr)

    # -- Upsample per-frame mask back to original sample count ------------
    orig_samples_per_frame = n_orig / n_frames if n_frames else 1
    speech_mask = np.zeros(n_orig, dtype=bool)
    for i in range(n_frames):
        s = int(round(i * orig_samples_per_frame))
        e = int(round((i + 1) * orig_samples_per_frame))
        e = min(e, n_orig)
        speech_mask[s:e] = is_speech[i]

    # -- Invert: silence = ~speech ----------------------------------------
    silence_mask = ~speech_mask

    # -- Gap merging: bridge short speech bursts between silence regions ---
    silence_mask, n_merged = _merge_short_gaps(
        silence_mask, sample_rate, min_gap_ms=min_gap_ms,
    )

    # -- Run-length filter: keep only silence runs >= min_silence_ms -------
    min_sil_samples = max(1, int(min_silence_ms * sample_rate / 1000))
    silence_runs = _find_mask_runs(silence_mask)
    filtered = np.zeros(n_orig, dtype=bool)
    n_kept = 0
    total_silence_samples = 0
    for s, e in silence_runs:
        if (e - s) >= min_sil_samples:
            filtered[s:e] = True
            n_kept += 1
            total_silence_samples += (e - s)

    total_silence_ms = total_silence_samples * 1000.0 / sample_rate
    elapsed_ms = (time.perf_counter() - t_start) * 1000
    logger.info(
        "VAD silence detection: %d regions, %.0fms total silence, %d gaps merged",
        n_kept, total_silence_ms, n_merged,
    )
    logger.info("[timing] stage=pipeline.vad duration_ms=%d", int(elapsed_ms))
    return filtered


# ---------------------------------------------------------------------------
# Grace/tail mask shaping for the excision pipeline
# ---------------------------------------------------------------------------

def _shape_injection_mask(
    coarse_mask: np.ndarray,
    fine_mask: np.ndarray,
    sample_rate: int,
    grace_ms: int = 150,
    tail_ms: int = 150,
    max_off_gap_ms: int = 160,
    min_on_ms: int = 120,
) -> np.ndarray:
    """Apply temporal hysteresis to produce a shaped excision mask.

    Shaping operates on the **coarse** mask (contiguous runs from
    run-length filtering) to determine *where* grace/tail zones go,
    then intersects the shaped zone with the **fine** mask to decide
    *which samples* actually get excised.

    Each coarse silence run is carved into three temporal zones::

        speech
         → [grace_ms] natural silence preserved   (no excision)
         → [interior] excision zone               (excised where fine=True)
         → [tail_ms]  clean silence buffer         (no excision)
         → speech

    Preserves natural sentence-ending pauses (punctuation inference),
    speaker handoff cues (diarization), and clean speech-onset transitions.

    Within each eligible zone a light temporal stabilizer fills brief
    off-gaps (≤ max_off_gap_ms) and removes brief on-spikes (< min_on_ms)
    to avoid rapid flicker when the signal hovers around the fine threshold.

    Coarse runs shorter than (grace_ms + tail_ms) receive NO excision —
    the silence is short enough that the encoder will survive.

    Args:
        coarse_mask: Boolean per-sample mask (contiguous runs, from coarse gate).
        fine_mask: Boolean per-sample mask (may be fragmented, from fine gate).
        sample_rate: Audio sample rate in Hz.
        grace_ms: Natural silence to preserve at start of each run.
        tail_ms: Clean silence buffer at end of each run.
        max_off_gap_ms: Maximum False-gap length to fill within eligible zone.
        min_on_ms: Minimum True-run length to keep within eligible zone.

    Returns:
        Shaped boolean mask — excision targets within grace/tail boundaries.
    """
    n = len(coarse_mask)
    if n == 0:
        return coarse_mask.copy()

    grace_samples = max(1, int(grace_ms * sample_rate / 1000))
    tail_samples = max(1, int(tail_ms * sample_rate / 1000))
    max_off_gap_samples = max(0, int(max_off_gap_ms * sample_rate / 1000))
    min_on_samples = max(0, int(min_on_ms * sample_rate / 1000))

    def _remove_short_true_runs(seg: np.ndarray, min_len: int) -> np.ndarray:
        if min_len <= 1:
            return seg
        m = len(seg)
        if m == 0:
            return seg
        padded_seg = np.empty(m + 2, dtype=bool)
        padded_seg[0] = False
        padded_seg[1:-1] = seg
        padded_seg[-1] = False
        diff_seg = np.diff(padded_seg.astype(np.int8))
        starts_seg = np.flatnonzero(diff_seg == 1)
        ends_seg = np.flatnonzero(diff_seg == -1)
        out_seg = seg.copy()
        for ss, ee in zip(starts_seg, ends_seg):
            if (ee - ss) < min_len:
                out_seg[ss:ee] = False
        return out_seg

    def _fill_short_false_gaps(seg: np.ndarray, max_gap: int) -> np.ndarray:
        """Fill short False gaps only when bounded by True on both sides."""
        if max_gap <= 0:
            return seg
        m = len(seg)
        if m == 0:
            return seg

        padded_seg = np.empty(m + 2, dtype=bool)
        padded_seg[0] = False
        padded_seg[1:-1] = seg
        padded_seg[-1] = False
        diff_seg = np.diff(padded_seg.astype(np.int8))
        starts_seg = np.flatnonzero(diff_seg == 1)
        ends_seg = np.flatnonzero(diff_seg == -1)

        if len(starts_seg) < 2:
            return seg

        out_seg = seg.copy()
        for i in range(len(starts_seg) - 1):
            gap_start = ends_seg[i]
            gap_end = starts_seg[i + 1]
            if 0 < (gap_end - gap_start) <= max_gap:
                out_seg[gap_start:gap_end] = True
        return out_seg

    # Find contiguous runs from the COARSE mask
    padded = np.empty(n + 2, dtype=bool)
    padded[0] = False
    padded[1:-1] = coarse_mask
    padded[-1] = False
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1)

    # Build the eligible excision zone from coarse runs
    eligible = np.zeros(n, dtype=bool)
    shaped_runs = 0
    skipped_short = 0
    eligible_runs: list[tuple[int, int]] = []

    for s, e in zip(starts, ends):
        run_len = e - s
        min_injectable = grace_samples + tail_samples

        if run_len <= min_injectable:
            # Too short for grace + tail — encoder survives this, skip
            skipped_short += 1
            continue

        inject_start = s + grace_samples
        inject_end = e - tail_samples
        eligible[inject_start:inject_end] = True
        eligible_runs.append((inject_start, inject_end))
        shaped_runs += 1

    # Intersect eligible zone with fine mask for actual excision targets
    shaped = eligible & fine_mask

    # Stabilize the shaped mask within each eligible run
    if max_off_gap_samples > 0 or min_on_samples > 1:
        shaped_before = shaped.copy()
        for rs, re_ in eligible_runs:
            seg = shaped[rs:re_]
            seg = _fill_short_false_gaps(seg, max_off_gap_samples)
            seg = _remove_short_true_runs(seg, min_on_samples)
            shaped[rs:re_] = seg

        if DEBUG_DSP:
            before = int(np.sum(shaped_before))
            after = int(np.sum(shaped))
            if before != after:
                before_runs = len(_find_mask_runs(shaped_before))
                after_runs = len(_find_mask_runs(shaped))
                logger.info(
                    "Excision mask stabilized: samples %d→%d, runs %d→%d "
                    "(max_off_gap=%dms, min_on=%dms)",
                    before, after, before_runs, after_runs,
                    max_off_gap_ms, min_on_ms,
                )

    # If the fine mask is too sparse relative to the eligible zone,
    # fall back to excising the entire eligible zone
    eligible_count = int(np.sum(eligible))
    shaped_count = int(np.sum(shaped))

    if shaped_runs > 0 and eligible_count > 0:
        coverage_ratio = shaped_count / eligible_count
        eligible_ms = eligible_count * 1000.0 / sample_rate
        shaped_ms = shaped_count * 1000.0 / sample_rate

        if coverage_ratio < 0.25:
            logger.info(
                "Fine mask covers only %.0f%% of eligible zone "
                "(%.0fms / %.0fms). Falling back to coarse-only excision.",
                coverage_ratio * 100, shaped_ms, eligible_ms,
            )
            shaped = eligible
        else:
            logger.info(
                "Fine mask covers %.0f%% of eligible zone (%.0fms / %.0fms)",
                coverage_ratio * 100, shaped_ms, eligible_ms,
            )

    logger.info(
        "Excision shaping: %d coarse runs → %d with excision zones "
        "(%d too short, grace=%dms, tail=%dms)",
        len(starts), shaped_runs, skipped_short, grace_ms, tail_ms,
    )

    return shaped


# ---------------------------------------------------------------------------
# Logarithmic silence compression helpers (kept for future use)
# ---------------------------------------------------------------------------

def _compress_silence_duration(
    original_ms: float,
    threshold_ms: float = 500.0,
    max_output_ms: float = 800.0,
) -> float:
    """Logarithmic compression: short pauses pass, long pauses approach cap."""
    if original_ms <= threshold_ms:
        return original_ms
    excess = original_ms - threshold_ms
    compressed = threshold_ms + max_output_ms * log1p(excess / max_output_ms)
    return min(compressed, max_output_ms)


def _compress_silence_regions(
    samples_2d: np.ndarray,
    sample_rate: int,
    coarse_mask: np.ndarray,
    threshold_ms: float = 500.0,
    max_output_ms: float = 800.0,
) -> np.ndarray:
    """Replace hard excision with proportional silence compression.

    For each silence run, compute a logarithmically compressed duration.
    Keep the first half and last half of the target duration (symmetric
    trim from the middle) to preserve speech-offset and speech-onset
    transitions.
    """
    silence_runs = _find_mask_runs(coarse_mask)
    speech_runs = _find_mask_runs(~coarse_mask)
    events = [(s, e, False) for s, e in speech_runs] + \
             [(s, e, True) for s, e in silence_runs]
    events.sort(key=lambda x: x[0])

    segments: list[np.ndarray] = []
    total_orig_ms = 0.0
    total_comp_ms = 0.0
    sil_idx = 0

    for start, end, is_silence in events:
        if not is_silence:
            segments.append(samples_2d[start:end])
            continue
        n_samples = end - start
        orig_ms = n_samples * 1000.0 / sample_rate
        comp_ms = _compress_silence_duration(orig_ms, threshold_ms, max_output_ms)
        if comp_ms >= orig_ms:
            segments.append(samples_2d[start:end])
        else:
            keep = max(1, int(comp_ms * sample_rate / 1000.0))
            half_a = keep // 2
            half_b = keep - half_a
            segments.append(samples_2d[start:start + half_a])
            segments.append(samples_2d[end - half_b:end])
            logger.info("Silence run %d: %.0fms → %.0fms", sil_idx, orig_ms, comp_ms)
        total_orig_ms += orig_ms
        total_comp_ms += comp_ms
        sil_idx += 1

    saved_ms = total_orig_ms - total_comp_ms
    if sil_idx:
        logger.info(
            "Compressed %d silence regions: %.0fms → %.0fms (%.0fms removed)",
            sil_idx, total_orig_ms, total_comp_ms, saved_ms,
        )
    return np.concatenate(segments, axis=0) if segments else samples_2d


# ---------------------------------------------------------------------------
# Windowed dBFS computation
# ---------------------------------------------------------------------------

def _compute_windowed_dbfs(
    samples: np.ndarray,
    sample_rate: int,
    window_ms: int = 100,
) -> np.ndarray:
    """Compute per-sample dBFS using windowed RMS (O(N) cumulative-sum method).

    Always normalises to absolute full-scale: integer samples are divided by
    their dtype max, float samples in int16 range by 32768.

    Args:
        samples: Mono audio samples (any numeric dtype).
        sample_rate: Sample rate in Hz.
        window_ms: RMS window size in ms.

    Returns:
        Array of dBFS values per sample.
    """
    n = len(samples)

    if np.issubdtype(samples.dtype, np.integer):
        samples = samples.astype(np.float32) / float(np.iinfo(samples.dtype).max)
    else:
        samples = samples.astype(np.float32)
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
# RMS-based silence detection (kept for external use, e.g. word alignment)
# ---------------------------------------------------------------------------

def detect_long_silences(
    samples: np.ndarray,
    sample_rate: int,
    silence_thresh_dbfs: float = -42,
    min_silence_ms: int = 1500,
    window_ms: int = 100,
    true_silence_dbfs: float = -55,
    adaptive_fallback: bool = True,
    adaptive_coarse_gap_db: float = 18.0,
    adaptive_fine_gap_db: float = 10.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Detect long silence regions with two-tier gating.

    Returns TWO masks:
    1. coarse_silence: Silence regions for initial detection.
    2. true_silence: Low-energy regions (subset of coarse).

    Adaptive thresholding validates fixed thresholds against the audio's
    dynamic range and switches to adaptive mode when they don't fit.

    This function is preserved for use by non-pipeline callers (e.g. word
    alignment).  The main pipeline uses VAD-based detection instead.

    Args:
        samples: Audio samples as numpy array (mono, any numeric dtype).
        sample_rate: Sample rate in Hz.
        silence_thresh_dbfs: Fixed coarse threshold.
        min_silence_ms: Minimum silence duration to detect.
        window_ms: Window size for RMS computation.
        true_silence_dbfs: Fixed fine threshold.
        adaptive_fallback: If True, validate and override fixed thresholds.
        adaptive_coarse_gap_db: dB above floor for adaptive coarse gate.
        adaptive_fine_gap_db: dB above floor for adaptive fine gate.

    Returns:
        Tuple of (coarse_silence_mask, true_silence_mask).
    """
    n = len(samples)
    if n == 0:
        return np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)

    dbfs = _compute_windowed_dbfs(samples, sample_rate, window_ms)

    _p10, _p50, _p90 = np.percentile(dbfs, [10, 50, 90])
    p10, p50, p90 = float(_p10), float(_p50), float(_p90)
    dynamic_range = p90 - p10

    logger.info(
        "Audio dBFS distribution: p10=%.1f, p50=%.1f, p90=%.1f, "
        "range=%.1fdB (fixed coarse=%.0f, fixed fine=%.0f)",
        p10, p50, p90, dynamic_range, silence_thresh_dbfs, true_silence_dbfs,
    )

    min_samples = max(1, int(min_silence_ms * sample_rate / 1000))

    def _apply_gates(coarse_thresh: float, fine_thresh: float) -> tuple[np.ndarray, np.ndarray]:
        coarse_mask = dbfs < coarse_thresh
        fine_mask = dbfs < fine_thresh

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

        filtered_fine = filtered_coarse & fine_mask
        return filtered_coarse, filtered_fine

    use_adaptive = False

    if adaptive_fallback:
        if dynamic_range < 10.0:
            logger.info("Adaptive mode: insufficient dynamic range (%.1fdB < 10dB)", dynamic_range)
            use_adaptive = True
        elif (silence_thresh_dbfs - p90) > -12.0:
            gap = p90 - silence_thresh_dbfs
            logger.info(
                "Adaptive mode: fixed coarse threshold too close to speech "
                "(only %.1fdB below p90=%.1fdB, need >= 12dB)",
                gap, p90,
            )
            use_adaptive = True
        elif p50 < silence_thresh_dbfs:
            logger.info(
                "Adaptive mode: fixed coarse threshold too high "
                "(p50=%.1fdB < coarse=%.0fdB, would mark >50%% as silence)",
                p50, silence_thresh_dbfs,
            )
            use_adaptive = True

    if not use_adaptive:
        filtered_coarse_mask, final_fine_mask = _apply_gates(silence_thresh_dbfs, true_silence_dbfs)

        coarse_count = int(np.sum(filtered_coarse_mask))
        if coarse_count > 0:
            silence_fraction = coarse_count / n
            if silence_fraction > 0.60:
                logger.info(
                    "Fixed thresholds marked %.0f%% of audio as silence "
                    "(suspiciously high), switching to adaptive",
                    silence_fraction * 100,
                )
                use_adaptive = True
            else:
                logger.info(
                    "Fixed thresholds: %.0f%% of audio marked as silence (reasonable)",
                    silence_fraction * 100,
                )
                return filtered_coarse_mask, final_fine_mask
        else:
            logger.info("Fixed thresholds detected no silence, trying adaptive")
            use_adaptive = True

    if dynamic_range < 6.0:
        logger.info(
            "Adaptive mode: dynamic range only %.1fdB, "
            "insufficient to distinguish speech from silence",
            dynamic_range,
        )
        return np.zeros(n, dtype=bool), np.zeros(n, dtype=bool)

    adaptive_coarse = p10 + adaptive_coarse_gap_db
    adaptive_fine = p10 + adaptive_fine_gap_db

    speech_guard = p90 - 12.0
    if adaptive_coarse > speech_guard:
        logger.info(
            "Adaptive coarse %.1fdB clamped to %.1fdB (12dB below speech peak)",
            adaptive_coarse, speech_guard,
        )
        adaptive_coarse = speech_guard

    adaptive_fine = min(adaptive_fine, adaptive_coarse - 3.0)

    logger.info(
        "Adaptive thresholds: floor=%.1fdB, speech=%.1fdB, "
        "dynamic_range=%.1fdB → coarse=%.1fdB, fine=%.1fdB",
        p10, p90, dynamic_range, adaptive_coarse, adaptive_fine,
    )

    filtered_coarse_mask, final_fine_mask = _apply_gates(adaptive_coarse, adaptive_fine)

    adaptive_coarse_ms = int(np.sum(filtered_coarse_mask)) * 1000.0 / sample_rate
    adaptive_fine_ms = int(np.sum(final_fine_mask)) * 1000.0 / sample_rate
    adaptive_silence_fraction = int(np.sum(filtered_coarse_mask)) / n if n > 0 else 0

    logger.info(
        "Adaptive detection: %.0fms coarse silence (%.0f%% of audio), "
        "%.0fms fine silence",
        adaptive_coarse_ms, adaptive_silence_fraction * 100, adaptive_fine_ms,
    )

    return filtered_coarse_mask, final_fine_mask
