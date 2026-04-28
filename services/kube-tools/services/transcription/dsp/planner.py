"""Greedy chunk planner — picks split points inside silence gaps.

Inputs:
* total audio duration (ms)
* speech regions (start_ms, end_ms) — the hysteresis output
* per-frame Silero probability stream (passed through to scorer)

Output:
* ``List[ChunkPlanEntry]`` — every decision (winner + losers).
* Materialisation into ``AudioChunk`` objects is done by
  ``materialize_chunks``; planning itself is audio-free and pure.

Defaults match the spec.  Pressure factor scales the effective confidence
threshold from 1.0× at ``min_chunk_ms`` down to 0.33× at ``max_chunk_ms``,
so mediocre boundaries near the limit beat awful ones — but if even the
best gap fails the relaxed threshold and we are at ``max_chunk_ms`` we
force a hard cut at exactly ``max_chunk_ms`` (boundary_type="forced").
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from pydub import AudioSegment

from services.transcription.models import AudioChunk, BoundaryScore, ChunkPlanEntry, ExcisionMap
from services.transcription.dsp.scoring import score_boundary

# Spec defaults — tuned for natural speech chunking.
# Target: 20–30 s clips produce 2–4 chunks with boundaries that fall on
# real pauses (not forced cuts), while still allowing the planner to
# absorb short phrases when needed.
MIN_CHUNK_MS = 8_000
MAX_CHUNK_MS = 16_000
OVERLAP_MS = 1_000

# Minimum silence required to qualify as a boundary candidate.
# Too high → missed natural pauses; too low → jittery splits.
MIN_BOUNDARY_SILENCE_MS = 600

# VAD confidence threshold for speech regions.
# Keep moderate to avoid dropping low-energy phonemes (e.g. trailing "t", "s").
CONFIDENCE_THRESHOLD = 0.55

# Pressure floor — at max_chunk_ms the boundary threshold is multiplied by this.
# Lower = more willing to accept suboptimal boundaries under pressure.
PRESSURE_FLOOR = 0.35

# Per-chunk silence excision: padding kept around each detected speech region.
# Inter-utterance silence collapses to ~2×EXCISION_PAD_MS.
# Always excise internal silence, including on the last chunk.
EXCISION_PAD_MS = 300

# Trailing pad applied ONLY to the final keep-run of the LAST chunk.
# Critical: we never trim the trailing silence after the last speech region.
# This preserves acoustic "closure" so the decoder emits final tokens reliably.
# This is real digital silence (not comfort noise) appended at export time.
FINAL_CHUNK_TAIL_MS = 800


# ---------------------------------------------------------------------------
# Gap derivation
# ---------------------------------------------------------------------------

def derive_silence_gaps(
    speech_regions_ms: List[Tuple[float, float]],
    total_ms: float,
) -> List[Tuple[float, float]]:
    """Return inter-speech gaps in original-audio coordinates.

    Includes the head before the first region and the tail after the last.
    Zero-length gaps are dropped.
    """
    boundaries = [0.0]
    for s, e in speech_regions_ms:
        boundaries.extend([s, e])
    boundaries.append(total_ms)

    gaps: List[Tuple[float, float]] = []
    for i in range(0, len(boundaries) - 1, 2):
        gs, ge = boundaries[i], boundaries[i + 1]
        if ge > gs:
            gaps.append((gs, ge))
    return gaps


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

def _pressure_factor(window_pos_ms: float, min_chunk_ms: int, max_chunk_ms: int) -> float:
    """Linearly scale 1.0 → PRESSURE_FLOOR as window_pos walks min → max."""
    if max_chunk_ms <= min_chunk_ms:
        return 1.0
    t = (window_pos_ms - min_chunk_ms) / (max_chunk_ms - min_chunk_ms)
    t = max(0.0, min(1.0, t))
    return 1.0 + (PRESSURE_FLOOR - 1.0) * t


def plan_chunks(
    speech_regions_ms: List[Tuple[float, float]],
    total_ms: float,
    probs: np.ndarray,
    frame_ms: float,
    min_chunk_ms: int = MIN_CHUNK_MS,
    max_chunk_ms: int = MAX_CHUNK_MS,
    min_boundary_silence_ms: int = MIN_BOUNDARY_SILENCE_MS,
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> List[ChunkPlanEntry]:
    """Greedy planner over silence gaps.  Pure function."""
    gaps = derive_silence_gaps(speech_regions_ms, total_ms)
    plan: List[ChunkPlanEntry] = []

    cursor = 0.0
    chunk_index = 0

    while cursor < total_ms:
        remaining = total_ms - cursor

        # Trivial: short tail — emit and stop.
        if remaining <= max_chunk_ms:
            plan.append(ChunkPlanEntry(
                chunk_index=chunk_index,
                start_ms=cursor,
                end_ms=total_ms,
                boundary_type="end_of_audio",
            ))
            break

        window_lo = cursor + min_chunk_ms
        window_hi = cursor + max_chunk_ms

        # Score every gap whose midpoint lies in [window_lo, window_hi].
        candidates: List[BoundaryScore] = []
        for gs, ge in gaps:
            mid = (gs + ge) / 2.0
            if mid < window_lo or mid > window_hi:
                continue
            candidates.append(score_boundary(
                gap_start_ms=gs,
                gap_end_ms=ge,
                probs=probs,
                frame_ms=frame_ms,
                min_boundary_silence_ms=min_boundary_silence_ms,
            ))

        chosen: BoundaryScore | None = None
        boundary_type = "natural"

        if candidates:
            # Apply pressure factor to each candidate's required threshold;
            # accept the highest-confidence candidate that beats its own
            # position-relative threshold.
            qualifiers: List[BoundaryScore] = []
            for c in candidates:
                eff = confidence_threshold * _pressure_factor(
                    c.midpoint_ms - cursor, min_chunk_ms, max_chunk_ms,
                )
                if c.confidence >= eff:
                    qualifiers.append(c)

            if qualifiers:
                chosen = max(qualifiers, key=lambda c: c.confidence)
            else:
                # At max_chunk_ms with nothing qualifying — force the best
                # available silence (still better than slicing through speech).
                chosen = max(candidates, key=lambda c: c.confidence)
                boundary_type = "forced"

        if chosen is None:
            # No silence in [min, max] at all — hard cut at max_chunk_ms.
            split_ms = window_hi
            boundary_type = "forced"
            rejected: List[BoundaryScore] = []
        else:
            split_ms = chosen.midpoint_ms
            rejected = [c for c in candidates if c is not chosen]

        plan.append(ChunkPlanEntry(
            chunk_index=chunk_index,
            start_ms=cursor,
            end_ms=split_ms,
            boundary_type=boundary_type,
            chosen_boundary=chosen,
            rejected_candidates=rejected,
        ))
        cursor = split_ms
        chunk_index += 1

    return plan


# ---------------------------------------------------------------------------
# Materialisation
# ---------------------------------------------------------------------------

def _build_chunk_keep_runs_ms(
    chunk_start_global_ms: float,
    chunk_end_global_ms: float,
    speech_regions_ms: List[Tuple[float, float]],
    pad_ms: int,
    trailing_pad_ms: Optional[int] = None,
    keep_trailing_silence: bool = False,
) -> List[Tuple[float, float]]:
    """Return chunk-local kept regions (sorted, merged) for excision.

    Each global speech region is clipped to the chunk window, padded by
    ``pad_ms`` on either side, and merged with neighbours that overlap or
    touch.  When the result is empty the caller should fall back to
    keeping the whole chunk (silent / no speech overlapping).

    ``trailing_pad_ms`` (if given) overrides ``pad_ms`` for the *right
    edge only* of the **last** kept region — used by the final chunk to
    preserve enough natural decay for the decoder to finalise cleanly.

    ``keep_trailing_silence`` extends the *right edge* of the last kept
    region all the way to the end of the chunk window.  This is what the
    final chunk uses: internal silences still collapse, but every sample
    after the final speech region is preserved as the EOS cue.
    """
    chunk_len = chunk_end_global_ms - chunk_start_global_ms
    if chunk_len <= 0 or pad_ms < 0:
        return []
    raw: List[Tuple[float, float]] = []
    for s, e in speech_regions_ms:
        # Convert to chunk-local with padding, clipped to chunk bounds.
        ls = max(0.0, s - pad_ms - chunk_start_global_ms)
        le = min(chunk_len, e + pad_ms - chunk_start_global_ms)
        if le > ls:
            raw.append((ls, le))
    if not raw:
        return []
    raw.sort()
    merged: List[Tuple[float, float]] = [raw[0]]
    for s, e in raw[1:]:
        ps, pe = merged[-1]
        if s <= pe:
            merged[-1] = (ps, max(pe, e))
        else:
            merged.append((s, e))
    if keep_trailing_silence and merged:
        # Extend the last kept region's right edge to the chunk end so
        # all post-speech audio survives as the EOS cue.
        last_s, last_e = merged[-1]
        if chunk_len > last_e:
            merged[-1] = (last_s, chunk_len)
    elif trailing_pad_ms is not None and trailing_pad_ms > pad_ms and merged:
        # Extend the last kept region's right edge with extra tail pad.
        last_s, last_e = merged[-1]
        # last_e currently sits at (speech_end + pad_ms); the matching
        # global speech end is (last_e + chunk_start_global - pad_ms).
        speech_end_global = last_e + chunk_start_global_ms - pad_ms
        new_e = min(chunk_len, speech_end_global + trailing_pad_ms - chunk_start_global_ms)
        if new_e > last_e:
            merged[-1] = (last_s, new_e)
    return merged


def _excise_chunk(
    chunk_audio: AudioSegment,
    keep_runs_ms: List[Tuple[float, float]],
) -> Tuple[AudioSegment, ExcisionMap]:
    """Cut and concatenate ``keep_runs_ms`` from ``chunk_audio``.

    Returns the excised AudioSegment and the chunk-local ExcisionMap.
    Slicing is byte-identical pydub slicing — no resampling, no DSP.
    """
    excised = AudioSegment.empty()
    for s, e in keep_runs_ms:
        excised += chunk_audio[int(s):int(e)]
    em = ExcisionMap(
        keep_regions_ms=list(keep_runs_ms),
        original_duration_ms=float(len(chunk_audio)),
        excised_duration_ms=float(len(excised)),
    )
    return excised, em


def materialize_chunks(
    audio_segment: AudioSegment,
    plan: List[ChunkPlanEntry],
    overlap_ms: int = OVERLAP_MS,
    speech_regions_ms: Optional[List[Tuple[float, float]]] = None,
    excision_pad_ms: int = EXCISION_PAD_MS,
    final_chunk_tail_ms: int = FINAL_CHUNK_TAIL_MS,
) -> List[AudioChunk]:
    """Cut ``audio_segment`` into ``AudioChunk``s following the plan.

    Each chunk's actual extraction window starts ``overlap_ms`` earlier
    than its logical start (clamped to 0).  Audio inside a chunk is
    bit-identical to the source — pydub slicing is a copy, no resampling.

    When ``speech_regions_ms`` is provided and ``excision_pad_ms > 0`` we
    additionally collapse intra-chunk silence: each chunk keeps only the
    union of (speech ± ``excision_pad_ms``) intersected with its window,
    and stores the chunk-local :class:`ExcisionMap` on
    ``AudioChunk.excision_map`` so downstream timestamp math can recover
    original time.

    Special handling for the **last** chunk: internal silences are still
    collapsed (so the visualisation shows the same red-stripe behaviour
    everywhere), but every sample *after* the final speech region is
    preserved as the EOS cue for the decoder.  Without this, the encoder
    occasionally finalises before emitting the trailing token — the
    "lost final segment" failure mode.
    """
    audio_len = float(len(audio_segment))
    excise_enabled = bool(speech_regions_ms) and excision_pad_ms > 0
    chunks: List[AudioChunk] = []
    last_idx = len(plan) - 1
    for i, entry in enumerate(plan):
        logical_start = entry.start_ms
        logical_end = min(entry.end_ms, audio_len)
        actual_start = max(0.0, logical_start - overlap_ms)
        actual_end = logical_end
        seg = audio_segment[int(actual_start):int(actual_end)]
        excision_map: Optional[ExcisionMap] = None
        is_final = i == last_idx
        if excise_enabled:
            keep_runs = _build_chunk_keep_runs_ms(
                actual_start, actual_end, speech_regions_ms, excision_pad_ms,
                trailing_pad_ms=final_chunk_tail_ms if is_final else None,
                keep_trailing_silence=is_final,
            )
            if keep_runs:
                seg, excision_map = _excise_chunk(seg, keep_runs)
        chunks.append(AudioChunk(
            audio_segment=seg,
            logical_start_ms=logical_start,
            logical_end_ms=logical_end,
            actual_start_ms=actual_start,
            actual_end_ms=actual_end,
            chunk_index=entry.chunk_index,
            excision_map=excision_map,
        ))
    return chunks
