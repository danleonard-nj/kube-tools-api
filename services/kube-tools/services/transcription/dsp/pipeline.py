"""Silence-budgeting preprocessor for gpt-4o-transcribe.

Strategy
--------
Don't filter, don't compress, don't level-shift speech.  Just cap dead
air.  Silero VAD identifies speech regions in the original audio; every
inter-region gap longer than ``max_silence_ms`` is symmetrically capped
(keep the head + tail, drop the middle).  Everything else passes through
untouched.

The single tuning knob is ``max_silence_ms``.  Don't add more.
"""

from __future__ import annotations

import base64
import re
import time
from math import gcd
from pathlib import Path
from typing import List, Tuple

import numpy as np
from pydub import AudioSegment
from scipy.signal import resample_poly

from framework.logger import get_logger
from services.transcription.models import ExcisionMap, PreprocessResult
from utilities.memory import release_memory

from services.transcription.dsp.debug import (
    DEBUG_DSP,
    _dump_debug_audio,
    _plot_excision_overlay,
)
from services.transcription.dsp.vad import (
    compute_speech_probabilities,
    hysteresis_speech_regions,
    FRAME_MS,
    VAD_SR,
)

logger = get_logger(__name__)


DEFAULT_MAX_SILENCE_MS = 800
P_HI = 0.5
P_LO = 0.35
MIN_SPEECH_MS = 120.0
MIN_SILENCE_MS = 300.0
COMFORT_NOISE_MS = 300
COMFORT_NOISE_DBFS = -58.0


def _budget_keep_regions(
    speech_regions_ms: List[Tuple[float, float]],
    total_ms: float,
    max_silence_ms: int,
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float, float]]]:
    """Return ``(keep_regions_ms, annotations)`` for the original timeline.

    Walk gaps between consecutive speech regions (including the head
    before the first and the tail after the last).  A gap longer than
    ``max_silence_ms`` is capped symmetrically — keep ``max_silence_ms/2``
    from each end, drop the middle.  Shorter gaps pass through intact.

    Annotations are ``(gap_start_ms, gap_end_ms, capped_ms)`` for every
    gap that was actually capped; the overlay uses these to label
    ``Xms → Yms`` on the raw waveform.
    """
    half_cap = max_silence_ms / 2.0

    # boundary pattern: gap, speech, gap, speech, ..., gap
    boundaries: List[float] = [0.0]
    for s, e in speech_regions_ms:
        boundaries.extend([s, e])
    boundaries.append(total_ms)

    keep: List[Tuple[float, float]] = []
    annotations: List[Tuple[float, float, float]] = []

    for i in range(0, len(boundaries) - 1, 2):
        gap_s, gap_e = boundaries[i], boundaries[i + 1]
        gap_len = gap_e - gap_s
        if gap_len > max_silence_ms:
            keep.append((gap_s, gap_s + half_cap))
            keep.append((gap_e - half_cap, gap_e))
            annotations.append((gap_s, gap_e, float(max_silence_ms)))
        elif gap_len > 0:
            keep.append((gap_s, gap_e))
        if i + 2 <= len(boundaries) - 1:
            sp_s, sp_e = boundaries[i + 1], boundaries[i + 2]
            if sp_e > sp_s:
                keep.append((sp_s, sp_e))

    # Merge touching regions so the ExcisionMap stays compact.
    merged: List[Tuple[float, float]] = []
    for s, e in keep:
        if merged and abs(s - merged[-1][1]) < 1e-6:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    return merged, annotations


def preprocess_for_transcription(
    audio_segment: AudioSegment,
    max_silence_ms: int = DEFAULT_MAX_SILENCE_MS,
    debug_tag: str | None = None,
    return_waveform_overlay: bool = False,
) -> PreprocessResult:
    """Cap long silences in ``audio_segment`` for safe single-shot ASR.

    Returns the processed audio (original samples concatenated, plus a
    short comfort-noise tail), an ``ExcisionMap`` for timestamp
    remapping, and an optional base64 PNG overlay.
    """
    t0 = time.perf_counter()
    sr = audio_segment.frame_rate
    channels = audio_segment.channels
    sample_width = audio_segment.sample_width
    total_ms = float(len(audio_segment))

    logger.info(
        "pipeline: max_silence=%dms audio=%.0fms sr=%d ch=%d",
        max_silence_ms, total_ms, sr, channels,
    )

    # ── Original PCM as int16, interleaved (n_frames, channels) ──────────
    raw_i16 = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)
    n_frames = len(raw_i16) // channels
    samples_2d = raw_i16.reshape((n_frames, channels))

    # Mono float32 @ 16 kHz for VAD only — samples_2d is left untouched
    # so the concatenation step can pull from original samples.
    mono = samples_2d.mean(axis=1).astype(np.float32) / np.float32(32768.0)
    if sr == VAD_SR:
        mono_16k = mono
    else:
        g = gcd(sr, VAD_SR)
        mono_16k = resample_poly(
            mono, up=VAD_SR // g, down=sr // g,
        ).astype(np.float32)

    # ── Debug setup ──────────────────────────────────────────────────────
    _dbg: Path | None = None
    if DEBUG_DSP:
        ts = time.strftime("%Y%m%d_%H%M%S")
        tag = re.sub(r"[^\w]+", "_", Path(debug_tag).stem).strip("_") if debug_tag else ""
        _dbg = Path(".") / "debug" / (f"{ts}_{tag}" if tag else ts)
        _dbg.mkdir(parents=True, exist_ok=True)
        logger.info("[DSP_DEBUG] Debug artifacts → %s", _dbg)
        _dump_debug_audio(mono, sr, _dbg / "01_raw.wav")

    # ── Stage 1: VAD ─────────────────────────────────────────────────────
    t_c = time.perf_counter()
    probs = compute_speech_probabilities(mono_16k)
    speech_regions_ms = hysteresis_speech_regions(
        probs, p_hi=P_HI, p_lo=P_LO,
        min_speech_ms=MIN_SPEECH_MS, min_silence_ms=MIN_SILENCE_MS,
    )
    # Clamp to audio duration — frame quantisation can push the final
    # region a frame past the end.
    speech_regions_ms = [
        (s, min(e, total_ms)) for s, e in speech_regions_ms if s < total_ms
    ]
    logger.info(
        "[timing] stage=pipeline.vad duration_ms=%d regions=%d",
        int((time.perf_counter() - t_c) * 1000), len(speech_regions_ms),
    )

    # ── Stage 2: budget gaps → keep-regions in ms ────────────────────────
    t_c = time.perf_counter()
    keep_ms, annotations = _budget_keep_regions(
        speech_regions_ms, total_ms, max_silence_ms,
    )
    removed_ms = sum((e - s) - capped for s, e, capped in annotations)
    logger.info(
        "[timing] stage=pipeline.budget duration_ms=%d gaps_capped=%d removed_ms=%.0f",
        int((time.perf_counter() - t_c) * 1000), len(annotations), removed_ms,
    )

    # Convert to original-audio sample indices.
    keep_runs: List[Tuple[int, int]] = []
    for s_ms, e_ms in keep_ms:
        s_idx = max(0, int(round(s_ms * sr / 1000.0)))
        e_idx = min(n_frames, int(round(e_ms * sr / 1000.0)))
        if e_idx > s_idx:
            keep_runs.append((s_idx, e_idx))
    if not keep_runs:  # nothing to keep — pass the whole recording through
        keep_runs = [(0, n_frames)]

    # ── Stage 3: concatenate from original samples ───────────────────────
    t_c = time.perf_counter()
    kept_2d = np.concatenate([samples_2d[s:e] for s, e in keep_runs], axis=0)

    # Trailing comfort noise (-58 dBFS, 300 ms) — same level on all channels.
    pad_samples = int(round(COMFORT_NOISE_MS * sr / 1000.0))
    noise_amp = 10.0 ** (COMFORT_NOISE_DBFS / 20.0)
    pad_f32 = (
        np.random.randn(pad_samples, channels).astype(np.float32)
        * np.float32(noise_amp)
    )
    pad_i16 = np.clip(pad_f32 * 32768.0, -32768, 32767).astype(np.int16)
    final_2d = np.concatenate([kept_2d, pad_i16], axis=0)
    logger.info(
        "[timing] stage=pipeline.concatenate duration_ms=%d kept_runs=%d out_ms=%.0f",
        int((time.perf_counter() - t_c) * 1000), len(keep_runs),
        len(final_2d) * 1000.0 / sr,
    )

    excision_map = ExcisionMap.from_keep_runs(keep_runs, sr, n_frames)
    result = AudioSegment(
        final_2d.flatten().tobytes(),
        frame_rate=sr,
        sample_width=sample_width,
        channels=channels,
    )

    logger.info(
        "[timing] stage=pipeline.total duration_ms=%d audio_ms=%.0f "
        "original=%.0fms kept=%.0fms",
        int((time.perf_counter() - t0) * 1000), total_ms,
        excision_map.original_duration_ms, excision_map.excised_duration_ms,
    )

    # ── Debug overlay + optional base64 PNG ─────────────────────────────
    waveform_overlay_b64: str | None = None
    final_mono = final_2d.astype(np.float32).mean(axis=1) / np.float32(32768.0)

    if _dbg is not None:
        _dump_debug_audio(final_mono, sr, _dbg / "02_final.wav")
        _plot_excision_overlay(
            raw=mono, sr=sr, probs=probs, frame_ms=FRAME_MS,
            annotations=annotations, p_hi=P_HI, p_lo=P_LO,
            final=final_mono, path=_dbg / "waveform_overlay.png",
        )

    if return_waveform_overlay:
        overlay_bytes = _plot_excision_overlay(
            raw=mono, sr=sr, probs=probs, frame_ms=FRAME_MS,
            annotations=annotations, p_hi=P_HI, p_lo=P_LO,
            final=final_mono, path=None, return_bytes=True,
        )
        if overlay_bytes:
            waveform_overlay_b64 = base64.b64encode(overlay_bytes).decode("utf-8")

    del mono, mono_16k, probs, raw_i16, samples_2d, kept_2d, pad_f32, pad_i16
    del final_2d, final_mono
    release_memory()

    return PreprocessResult(
        audio=result,
        excision_map=excision_map,
        waveform_overlay=waveform_overlay_b64,
    )
