"""Pure-function confidence scoring for VAD silence-gap split candidates.

Each gap between speech regions is scored on four features in [0, 1]:

* ``duration``         — sigmoid around ``min_boundary_silence_ms`` (500 ms).
* ``stability``        — 1 − normalised variance of P(speech) inside the gap.
* ``restart_strength`` — rise rate of P(speech) at the trailing edge.
* ``depth``            — 1 − mean P(speech) inside the gap.

The overall ``confidence`` is the equally-weighted mean of the four (each
weight = 0.25).  Weights live as module constants so they can be tuned
without touching call sites.

This module has no audio or model dependencies — only numpy — and is
fully deterministic.  The downstream planner is the sole caller.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from services.transcription.models import BoundaryScore


# ---------------------------------------------------------------------------
# Tuneable constants (tune after measurement)
# ---------------------------------------------------------------------------

W_DURATION = 0.25
W_STABILITY = 0.25
W_RESTART = 0.25
W_DEPTH = 0.25

# Sigmoid soft-knee around the boundary-silence target (ms).
DURATION_SIGMOID_K_MS = 200.0

# Number of frames at the gap's trailing edge used to estimate restart slope.
RESTART_WINDOW_FRAMES = 4

# Worst-case variance for a Bernoulli-like signal in [0, 1].
_MAX_VAR = 0.25


# ---------------------------------------------------------------------------
# Per-feature scorers
# ---------------------------------------------------------------------------

def _duration_score(gap_ms: float, min_boundary_silence_ms: float) -> float:
    """Sigmoid centred at ``min_boundary_silence_ms``.

    Slow shoulder: a 500 ms gap scores 0.5; a 700 ms gap ≈ 0.73; a 300 ms
    gap ≈ 0.27.  ``DURATION_SIGMOID_K_MS`` controls the slope.
    """
    z = (gap_ms - min_boundary_silence_ms) / DURATION_SIGMOID_K_MS
    # Clamp to avoid overflow on absurd values.
    z = max(-50.0, min(50.0, z))
    return float(1.0 / (1.0 + np.exp(-z)))


def _stability_score(probs_in_gap: Sequence[float]) -> float:
    """1 − normalised variance of P(speech) over the gap."""
    if len(probs_in_gap) < 2:
        return 1.0
    var = float(np.var(np.asarray(probs_in_gap, dtype=np.float32)))
    return float(max(0.0, 1.0 - min(var / _MAX_VAR, 1.0)))


def _restart_score(probs_after_gap: Sequence[float]) -> float:
    """Rise rate of P(speech) immediately after the gap.

    Uses the slope of the first ``RESTART_WINDOW_FRAMES`` frames after the
    gap end, normalised to [0, 1].  A flat or falling trace scores 0; a
    fast climb to ~1.0 scores 1.0.  If no frames remain (gap reaches end of
    audio) we return 0 — there is no speech to restart into.
    """
    arr = np.asarray(probs_after_gap, dtype=np.float32)[:RESTART_WINDOW_FRAMES]
    if arr.size < 2:
        return 0.0
    rise = float(arr[-1] - arr[0])
    return float(max(0.0, min(1.0, rise)))


def _depth_score(probs_in_gap: Sequence[float]) -> float:
    """1 − mean P(speech) inside the gap (deeper silence ⇒ higher score)."""
    if len(probs_in_gap) == 0:
        return 0.0
    mean = float(np.mean(np.asarray(probs_in_gap, dtype=np.float32)))
    return float(max(0.0, min(1.0, 1.0 - mean)))


# ---------------------------------------------------------------------------
# Public scorer
# ---------------------------------------------------------------------------

def score_boundary(
    gap_start_ms: float,
    gap_end_ms: float,
    probs: np.ndarray,
    frame_ms: float,
    min_boundary_silence_ms: float = 500.0,
) -> BoundaryScore:
    """Score one silence gap as a split candidate.

    ``probs`` is the full per-frame Silero stream so we can reach into it
    without extra slicing on the caller side.  ``frame_ms`` is the frame
    period (32 ms for Silero V5 @ 16 kHz).
    """
    gap_ms = max(0.0, gap_end_ms - gap_start_ms)
    n_frames = len(probs)

    f_start = max(0, int(round(gap_start_ms / frame_ms)))
    f_end = max(f_start, min(n_frames, int(round(gap_end_ms / frame_ms))))

    in_gap = probs[f_start:f_end]
    after = probs[f_end:f_end + RESTART_WINDOW_FRAMES]

    duration = _duration_score(gap_ms, min_boundary_silence_ms)
    stability = _stability_score(in_gap)
    restart = _restart_score(after)
    depth = _depth_score(in_gap)

    confidence = (
        W_DURATION * duration
        + W_STABILITY * stability
        + W_RESTART * restart
        + W_DEPTH * depth
    )

    return BoundaryScore(
        gap_start_ms=float(gap_start_ms),
        gap_end_ms=float(gap_end_ms),
        midpoint_ms=float((gap_start_ms + gap_end_ms) / 2.0),
        duration=duration,
        stability=stability,
        restart_strength=restart,
        depth=depth,
        confidence=float(confidence),
    )
