"""VAD-planned chunking pipeline (replaces silence excision).

Audio in → Silero VAD → P(speech) → hysteresis → speech regions →
greedy planner picks split points inside silence gaps → ``AudioChunk`` list
with leading overlap.  Audio inside each chunk is bit-identical to the
source: no DSP, no compressor, no comfort noise — hesitations preserved.

The single tuning knobs are exposed via ``preprocess_for_transcription``
parameters; defaults are spec-pinned constants.
"""

from __future__ import annotations

import base64
import re
import time
from math import gcd
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from pydub import AudioSegment
from scipy.signal import resample_poly

from framework.logger import get_logger
from services.transcription.models import AudioChunk, ChunkPlanEntry, ExcisionMap, PreprocessResult
from services.transcription.dsp.debug import DEBUG_DSP, _dump_debug_audio
from services.transcription.dsp.overlay import render_chunk_plan_overlay, render_chunk_plan_table
from services.transcription.dsp.planner import (
    MAX_CHUNK_MS, MIN_BOUNDARY_SILENCE_MS, MIN_CHUNK_MS, OVERLAP_MS,
    CONFIDENCE_THRESHOLD, EXCISION_PAD_MS, materialize_chunks, plan_chunks,
)
from services.transcription.dsp.vad import (
    FRAME_MS, VAD_SR, compute_speech_probabilities, hysteresis_speech_regions,
)

logger = get_logger(__name__)


# Hysteresis thresholds (kept stable across pipeline_version v2).
P_HI = 0.5
P_LO = 0.35
MIN_SPEECH_MS = 120.0
MIN_SILENCE_MS = 300.0


def _to_mono_16k(audio_segment: AudioSegment) -> np.ndarray:
    """Return mono float32 @ 16 kHz for VAD.

    Builds the native-SR mono array, resamples (if needed), and frees
    the native-SR copy before returning — only the 16 kHz buffer is
    retained, which is what both VAD and the (decimated) overlay use.
    """
    sr = audio_segment.frame_rate
    raw_i16 = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)
    n_frames = len(raw_i16) // audio_segment.channels
    samples_2d = raw_i16.reshape((n_frames, audio_segment.channels))
    mono = samples_2d.mean(axis=1).astype(np.float32) / np.float32(32768.0)
    del raw_i16, samples_2d
    if sr == VAD_SR:
        return mono
    g = gcd(sr, VAD_SR)
    mono_16k = resample_poly(mono, up=VAD_SR // g, down=sr // g).astype(np.float32)
    del mono
    return mono_16k


def _setup_debug_dir(debug_tag: Optional[str]) -> Optional[Path]:
    if not DEBUG_DSP:
        return None
    ts = time.strftime("%Y%m%d_%H%M%S")
    tag = re.sub(r"[^\w]+", "_", Path(debug_tag).stem).strip("_") if debug_tag else ""
    dbg = Path(".") / "debug" / (f"{ts}_{tag}" if tag else ts)
    dbg.mkdir(parents=True, exist_ok=True)
    logger.info("[DSP_DEBUG] artifacts → %s", dbg)
    return dbg


def preprocess_for_transcription(
    audio_segment: AudioSegment,
    min_chunk_ms: int = MIN_CHUNK_MS,
    max_chunk_ms: int = MAX_CHUNK_MS,
    overlap_ms: int = OVERLAP_MS,
    min_boundary_silence_ms: int = MIN_BOUNDARY_SILENCE_MS,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
    excision_pad_ms: int = EXCISION_PAD_MS,
    debug_tag: Optional[str] = None,
    return_waveform_overlay: bool = False,
) -> PreprocessResult:
    """Plan chunks for ``audio_segment`` and return materialised chunks.

    ``PreprocessResult.audio`` is the original (unmodified) segment — the
    planner-built ``AudioChunk`` list lives on ``chunks``, the per-chunk
    decision log on ``chunk_plan``, and the per-frame VAD trace on
    ``vad_probs``.  ``ExcisionMap`` is the identity map.
    """
    t0 = time.perf_counter()
    sr = audio_segment.frame_rate
    total_ms = float(len(audio_segment))
    logger.info(
        "pipeline: audio=%.0fms sr=%d ch=%d window=[%d, %d]ms overlap=%dms",
        total_ms, sr, audio_segment.channels, min_chunk_ms, max_chunk_ms, overlap_ms,
    )

    mono_16k = _to_mono_16k(audio_segment)
    dbg = _setup_debug_dir(debug_tag)
    if dbg is not None:
        _dump_debug_audio(mono_16k, VAD_SR, dbg / "01_raw_16k.wav")

    # ── VAD ────────────────────────────────────────────────────────────
    t_c = time.perf_counter()
    probs = compute_speech_probabilities(mono_16k)
    speech_regions_ms = hysteresis_speech_regions(
        probs, p_hi=P_HI, p_lo=P_LO,
        min_speech_ms=MIN_SPEECH_MS, min_silence_ms=MIN_SILENCE_MS,
    )
    speech_regions_ms = [(s, min(e, total_ms)) for s, e in speech_regions_ms if s < total_ms]
    logger.info("[timing] stage=pipeline.vad duration_ms=%d regions=%d",
                int((time.perf_counter() - t_c) * 1000), len(speech_regions_ms))

    # ── Plan ───────────────────────────────────────────────────────────
    t_c = time.perf_counter()
    plan: List[ChunkPlanEntry] = plan_chunks(
        speech_regions_ms=speech_regions_ms,
        total_ms=total_ms,
        probs=probs,
        frame_ms=FRAME_MS,
        min_chunk_ms=min_chunk_ms,
        max_chunk_ms=max_chunk_ms,
        min_boundary_silence_ms=min_boundary_silence_ms,
        confidence_threshold=confidence_threshold,
    )
    chunks: List[AudioChunk] = materialize_chunks(
        audio_segment, plan, overlap_ms=overlap_ms,
        speech_regions_ms=speech_regions_ms,
        excision_pad_ms=excision_pad_ms,
    )
    excised_total = sum(len(c.audio_segment) for c in chunks)
    raw_total = sum(c.actual_end_ms - c.actual_start_ms for c in chunks)
    saved_pct = (1.0 - excised_total / raw_total) * 100.0 if raw_total > 0 else 0.0
    last_chunk_ms = int(len(chunks[-1].audio_segment)) if chunks else 0
    last_excised = chunks and chunks[-1].excision_map is not None
    logger.info(
        "[timing] stage=pipeline.plan duration_ms=%d chunks=%d excised_ms=%d raw_ms=%d saved=%.1f%% last_chunk_ms=%d last_excised=%s",
        int((time.perf_counter() - t_c) * 1000), len(chunks),
        int(excised_total), int(raw_total), saved_pct, last_chunk_ms, bool(last_excised),
    )

    # ── Overlay (optional) ─────────────────────────────────────────────
    waveform_overlay_b64: Optional[str] = None
    if dbg is not None:
        render_chunk_plan_overlay(
            raw=mono_16k, sr=VAD_SR, probs=probs, frame_ms=FRAME_MS, plan=plan,
            p_hi=P_HI, p_lo=P_LO, path=dbg / "chunk_plan.png", chunks=chunks,
        )
        (dbg / "chunk_plan.md").write_text(render_chunk_plan_table(plan), encoding="utf-8")

    if return_waveform_overlay:
        png = render_chunk_plan_overlay(
            raw=mono_16k, sr=VAD_SR, probs=probs, frame_ms=FRAME_MS, plan=plan,
            p_hi=P_HI, p_lo=P_LO, path=None, return_bytes=True, chunks=chunks,
        )
        if png:
            waveform_overlay_b64 = base64.b64encode(png).decode("utf-8")

    logger.info("[timing] stage=pipeline.total duration_ms=%d audio_ms=%.0f chunks=%d",
                int((time.perf_counter() - t0) * 1000), total_ms, len(chunks))

    return PreprocessResult(
        audio=audio_segment,
        excision_map=ExcisionMap.identity(total_ms),
        waveform_overlay=waveform_overlay_b64,
        chunks=chunks,
        chunk_plan=plan,
        vad_probs=probs,
    )
