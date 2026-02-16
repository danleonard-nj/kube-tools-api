"""Dynamic range compression and transient limiting.

These functions return gain envelopes so the pipeline can compose
``limiter_gain * compressor_gain`` and apply once to all channels,
avoiding redundant mono processing.
"""

import numpy as np
from scipy.ndimage import minimum_filter1d

from framework.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional Numba acceleration for the attack/release smoothing loop
# ---------------------------------------------------------------------------
try:
    from numba import njit as _njit
    _HAS_NUMBA = True
except ImportError:
    _HAS_NUMBA = False


def _smooth_gain_py(gain: np.ndarray, a_att: float, a_rel: float) -> np.ndarray:
    """Attack/release smoothing — pure Python fallback.

    This is the per-sample loop bottleneck (~768k iterations for 16 s at
    48 kHz, taking 1.3–2.6 s per request in production).  Candidate for
    numba ``@njit`` acceleration — see below.
    """
    n = len(gain)
    sg = np.empty(n, dtype=np.float32)
    sg[0] = gain[0]
    for i in range(1, n):
        a = a_att if gain[i] < sg[i - 1] else a_rel
        sg[i] = sg[i - 1] + a * (gain[i] - sg[i - 1])
    return sg


if _HAS_NUMBA:
    _smooth_gain = _njit(cache=True, fastmath=True)(_smooth_gain_py)
    # Warmup: trigger JIT compilation on a tiny input so the first real
    # request doesn't pay the ~1–2 s compile cost.
    _smooth_gain(
        np.zeros(16, dtype=np.float32),
        np.float32(0.1),
        np.float32(0.01),
    )
    logger.info("Numba JIT compiled _smooth_gain (compressor smoothing loop)")
else:
    _smooth_gain = _smooth_gain_py


# ---------------------------------------------------------------------------
# Transient limiter
# ---------------------------------------------------------------------------

def limit_transients(
    samples_mono: np.ndarray,
    sample_rate: int,
    ceiling_db: float = -6.0,
    lookahead_ms: float = 2.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Brick-wall limiter with lookahead to catch sub-ms transient spikes.

    Prevents clipping artifacts that confuse the ASR encoder by reducing
    gain on samples that exceed the ceiling.  A forward-looking minimum
    filter ensures gain reduction begins *before* the transient arrives.

    Args:
        samples_mono: Float32 mono samples in [-1, 1].
        sample_rate: Audio sample rate in Hz.
        ceiling_db: Maximum output level in dBFS.
        lookahead_ms: Lookahead window in ms for the minimum filter.

    Returns:
        Tuple of (limited_mono, gain_envelope).
        - limited_mono: Gain-reduced float32 samples.
        - gain_envelope: Per-sample gain array (1.0 where unmodified,
          < 1.0 where limited).
    """
    ceiling_lin = np.float32(10.0 ** (ceiling_db / 20.0))
    abs_samples = np.abs(samples_mono)

    # Per-sample gain: reduce where amplitude exceeds ceiling
    gain = np.ones_like(samples_mono)
    above = abs_samples > ceiling_lin
    gain[above] = ceiling_lin / (abs_samples[above] + np.float32(1e-10))

    # Lookahead: take minimum gain in a forward window so gain reduction
    # begins *before* the transient arrives.
    lookahead_samples = max(1, int(lookahead_ms * sample_rate / 1000.0))
    gain = minimum_filter1d(
        gain, size=lookahead_samples * 2, origin=-lookahead_samples,
    )

    limited = (samples_mono * gain).astype(np.float32)
    return limited, gain


# ---------------------------------------------------------------------------
# Dynamic range compressor
# ---------------------------------------------------------------------------

def compress_dynamic_range(
    samples_mono: np.ndarray,
    sample_rate: int,
    ratio: float = 3.0,
    threshold_db: float = -30.0,
    attack_ms: float = 10.0,
    release_ms: float = 100.0,
    makeup_target_db: float = -16.0,
) -> tuple[np.ndarray, np.ndarray]:
    """RMS envelope-follower compressor with speech-aware makeup gain.

    Tames loud-after-quiet transitions that trigger gpt-4o-transcribe
    <|endoftext|> hallucinations.  The compressor reduces gain above
    *threshold_db* by *ratio*, smoothed with attack/release ballistics.

    Makeup gain is computed from speech-only RMS (ignoring silence) so that
    long quiet passages don't inflate the multiplier and clip speech.

    Args:
        samples_mono: Float32 mono samples in [-1, 1] (post-limiter).
        sample_rate: Audio sample rate in Hz.
        ratio: Compression ratio (e.g. 3.0 = 3:1).
        threshold_db: Level above which compression begins, in dBFS.
        attack_ms: Attack time constant in ms.
        release_ms: Release time constant in ms.
        makeup_target_db: Target speech RMS after makeup gain, in dBFS.

    Returns:
        Tuple of (compressed_mono, gain_envelope).
        - compressed_mono: Compressed float32 samples (clipped to [-1, 1]
          for downstream silence detection).
        - gain_envelope: Per-sample gain array (smoothed_gain × makeup).
          This is the *unclipped* gain — the pipeline applies it to all
          channels and clips separately.
    """
    num_frames = len(samples_mono)
    thresh_lin = np.float32(10.0 ** (threshold_db / 20.0))
    env_w = max(1, int(sample_rate * 0.005))  # 5 ms RMS window
    a_att = np.float32(1.0 - np.exp(-1.0 / (attack_ms * sample_rate / 1000.0)))
    a_rel = np.float32(1.0 - np.exp(-1.0 / (release_ms * sample_rate / 1000.0)))

    # --- RMS envelope (cumulative-sum, O(N)) ---
    sq = (samples_mono * samples_mono).astype(np.float64)
    cs = np.empty(num_frames + 1, dtype=np.float64)
    cs[0] = 0.0
    np.cumsum(sq, out=cs[1:])
    ix = np.arange(num_frames)
    lo = np.clip(ix - env_w // 2, 0, num_frames)
    hi = np.clip(ix + env_w // 2 + 1, 0, num_frames)
    cnt = (hi - lo).astype(np.float64)
    cnt[cnt == 0] = 1.0
    rms_env = np.sqrt((cs[hi] - cs[lo]) / cnt).astype(np.float32)

    # --- Gain curve ---
    gain = np.ones(num_frames, dtype=np.float32)
    above = rms_env > thresh_lin
    gain[above] = (thresh_lin / (rms_env[above] + np.float32(1e-10))) ** \
        np.float32(1.0 - 1.0 / ratio)

    # --- Attack/release smoothing (per-sample loop — bottleneck) ---
    sg = _smooth_gain(gain, a_att, a_rel)

    # --- Speech-aware makeup gain ---
    # Measure RMS of speech only (silence would drag it down and produce
    # an enormous makeup multiplier that clips speech).
    comp_mono = samples_mono * sg
    speech_mask = np.abs(comp_mono) > np.float32(0.01)  # ~-40 dBFS floor
    if int(np.sum(speech_mask)) > 0:
        rms_out = np.float32(np.sqrt(np.mean(comp_mono[speech_mask] ** 2)))
    else:
        rms_out = np.float32(np.sqrt(np.mean(comp_mono ** 2)))

    makeup = (
        np.float32(10.0 ** (makeup_target_db / 20.0)) / rms_out
        if rms_out > 1e-10
        else np.float32(1.0)
    )

    total_gain = sg * np.float32(makeup)
    compressed = np.clip(
        samples_mono * total_gain, -1.0, 1.0
    ).astype(np.float32)

    return compressed, total_gain
