"""Silero VAD wrapper + hysteresis-based speech region extraction.

We use Silero's per-frame probability output (not its built-in
speech-timestamp helper) so the hysteresis is explicit and inspectable.

The Silero V5 model requires fixed window sizes: 512 samples at 16 kHz
(=32 ms).  We expose this as ``FRAME_MS`` for callers that need to
convert frame indices ↔ time.

If ``silero-vad`` (or its torch dependency) cannot be imported, this
module raises at import time — there is intentionally no fallback.
"""

from __future__ import annotations

import threading
from typing import List, Tuple

import numpy as np

# Eager imports — fail loudly at import time if the dependency is missing.
import torch
from silero_vad import load_silero_vad


VAD_SR = 16_000
WINDOW_SAMPLES = 512                        # Silero V5 requirement @ 16 kHz
FRAME_MS = WINDOW_SAMPLES * 1000.0 / VAD_SR  # 32.0 ms


# ---------------------------------------------------------------------------
# Lazy singleton
# ---------------------------------------------------------------------------
_model = None
_model_lock = threading.Lock()


def _get_model():
    """Return the Silero VAD model, loading it on first use."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = load_silero_vad()
    return _model


# ---------------------------------------------------------------------------
# Per-frame probability stream
# ---------------------------------------------------------------------------

def compute_speech_probabilities(mono_16k_f32: np.ndarray) -> np.ndarray:
    """Run Silero over a mono float32 array at 16 kHz.

    Returns one probability per ``WINDOW_SAMPLES``-sample frame.  Trailing
    samples that don't fill a full frame are zero-padded so the final
    frame still gets a probability.
    """
    if mono_16k_f32.dtype != np.float32:
        mono_16k_f32 = mono_16k_f32.astype(np.float32, copy=False)

    n = len(mono_16k_f32)
    n_full = n // WINDOW_SAMPLES
    n_frames = n_full + (1 if n % WINDOW_SAMPLES else 0)
    if n_frames == 0:
        return np.zeros(0, dtype=np.float32)

    # Pad to a full frame boundary so reshape works.
    pad = n_frames * WINDOW_SAMPLES - n
    if pad:
        mono_16k_f32 = np.concatenate(
            [mono_16k_f32, np.zeros(pad, dtype=np.float32)]
        )

    model = _get_model()
    model.reset_states()  # important: state carries across calls otherwise

    probs = np.empty(n_frames, dtype=np.float32)
    # Process one window at a time — Silero is stateful and requires
    # exactly WINDOW_SAMPLES per call at this sample rate.
    for i in range(n_frames):
        chunk = mono_16k_f32[i * WINDOW_SAMPLES:(i + 1) * WINDOW_SAMPLES]
        with torch.no_grad():
            probs[i] = float(model(torch.from_numpy(chunk), VAD_SR).item())
    return probs


# ---------------------------------------------------------------------------
# Hysteresis → speech regions
# ---------------------------------------------------------------------------

def hysteresis_speech_regions(
    probs: np.ndarray,
    p_hi: float = 0.5,
    p_lo: float = 0.35,
    min_speech_ms: float = 120.0,
    min_silence_ms: float = 300.0,
) -> List[Tuple[float, float]]:
    """Convert a per-frame probability stream to ``[(start_ms, end_ms), ...]``.

    Open at ``p >= p_hi``, close at ``p < p_lo``.  Require the open
    condition to persist ``min_speech_ms`` before committing a region,
    and the close condition to persist ``min_silence_ms`` before ending
    one.  Times are measured in original-audio milliseconds (frame index
    × ``FRAME_MS``).
    """
    n = len(probs)
    if n == 0:
        return []

    min_speech_frames = max(1, int(round(min_speech_ms / FRAME_MS)))
    min_silence_frames = max(1, int(round(min_silence_ms / FRAME_MS)))

    in_speech = False
    speech_start: int | None = None
    above_hi_run = 0   # consecutive frames with p >= p_hi (while in silence)
    below_lo_run = 0   # consecutive frames with p < p_lo  (while in speech)
    candidate_start: int | None = None
    candidate_end: int | None = None

    regions: List[Tuple[int, int]] = []

    for i, p in enumerate(probs):
        if not in_speech:
            if p >= p_hi:
                if above_hi_run == 0:
                    candidate_start = i
                above_hi_run += 1
                if above_hi_run >= min_speech_frames:
                    in_speech = True
                    speech_start = candidate_start
                    above_hi_run = 0
                    below_lo_run = 0
                    candidate_end = None
            else:
                above_hi_run = 0
                candidate_start = None
        else:
            if p < p_lo:
                if below_lo_run == 0:
                    candidate_end = i  # frame at which silence began
                below_lo_run += 1
                if below_lo_run >= min_silence_frames:
                    regions.append((speech_start, candidate_end))
                    in_speech = False
                    speech_start = None
                    below_lo_run = 0
                    above_hi_run = 0
                    candidate_end = None
            else:
                below_lo_run = 0
                candidate_end = None

    if in_speech and speech_start is not None:
        regions.append((speech_start, n))

    # Convert frame indices → milliseconds.
    return [(s * FRAME_MS, e * FRAME_MS) for s, e in regions]
