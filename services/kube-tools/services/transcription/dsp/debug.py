"""Debug helpers for the DSP pipeline.

Controlled by the ``DSP_DEBUG`` environment variable.  When enabled,
intermediate audio stages and a 3-panel waveform overlay are written to
disk for offline inspection.  Disabled by default in production.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import List, Tuple

import numpy as np

from framework.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Debug flag — disabled by default, enable via environment variable
# ---------------------------------------------------------------------------
DEBUG_DSP = os.environ.get("DSP_DEBUG", "").lower() in ("1", "true", "yes")

try:
    import soundfile as _sf
    _HAS_SOUNDFILE = True
except ImportError:
    _sf = None
    _HAS_SOUNDFILE = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    _HAS_MATPLOTLIB = True
except ImportError:
    _plt = None
    _HAS_MATPLOTLIB = False


def _dump_debug_audio(samples: np.ndarray, sr: int, path: Path) -> None:
    """Write mono float32 samples to a WAV file via soundfile."""
    if not _HAS_SOUNDFILE:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _sf.write(str(path), samples, sr, subtype="FLOAT")
        logger.info(
            "[DSP_DEBUG] Dumped %s (size=%d, duration_ms=%d, sr=%d)",
            path.name, path.stat().st_size,
            int(len(samples) * 1000 / sr), sr,
        )
    except Exception as exc:
        logger.info("[DSP_DEBUG] Failed to write %s: %s", path.name, exc)


def _plot_excision_overlay(
    raw: np.ndarray,
    sr: int,
    probs: np.ndarray,
    frame_ms: float,
    annotations: List[Tuple[float, float, float]],
    p_hi: float,
    p_lo: float,
    final: np.ndarray,
    path: Path | None,
    return_bytes: bool = False,
) -> bytes | None:
    """3-panel overlay plot.

    1. Raw waveform (gray).  Every gap that was capped is shaded blue
       and annotated with ``Xms → Yms``; gaps left untouched are faintly
       shaded red.  (Here we only have capped-gap annotations; untouched
       silence regions aren't explicitly tracked, so only capped gaps
       are drawn.)
    2. Silero per-frame probability trace (0–1) with dashed lines at
       ``p_hi`` and ``p_lo``.
    3. Final processed waveform (blue).

    Panels 1 and 2 share the original-audio time axis.  Panel 3 uses
    its own (shorter) time axis.
    """
    if not _HAS_MATPLOTLIB:
        return None
    try:
        fig, (ax1, ax2, ax3) = _plt.subplots(3, 1, figsize=(16, 8))
        t_raw = np.arange(len(raw)) / sr
        y_max_raw = float(max(np.abs(raw).max(), 1e-6)) * 1.05
        y_max_fin = float(max(np.abs(final).max(), 1e-6)) * 1.05

        # ── Panel 1: raw + gap shading ──────────────────────────────────
        ax1.plot(t_raw, raw, linewidth=0.3, color="gray", label="raw")
        for gap_s_ms, gap_e_ms, capped_ms in annotations:
            ax1.axvspan(
                gap_s_ms / 1000.0, gap_e_ms / 1000.0,
                color="blue", alpha=0.15,
            )
            mid = (gap_s_ms + gap_e_ms) / 2000.0
            orig_ms = gap_e_ms - gap_s_ms
            ax1.text(
                mid, y_max_raw * 0.85,
                f"{int(orig_ms)}ms → {int(capped_ms)}ms",
                ha="center", va="top", fontsize=8, color="navy",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="navy", alpha=0.7),
            )
        x_end = t_raw[-1] if len(raw) else 1.0
        ax1.set_xlim(0, x_end)
        ax1.set_ylim(-y_max_raw, y_max_raw)
        ax1.set_title("Raw waveform + capped gaps")

        # ── Panel 2: probability trace with hysteresis thresholds ────────
        t_probs = (np.arange(len(probs)) * frame_ms + frame_ms / 2.0) / 1000.0
        ax2.plot(t_probs, probs, linewidth=0.6, color="#222")
        ax2.axhline(p_hi, linestyle="--", linewidth=0.8, color="green",
                    label=f"p_hi={p_hi}")
        ax2.axhline(p_lo, linestyle="--", linewidth=0.8, color="red",
                    label=f"p_lo={p_lo}")
        ax2.set_xlim(0, x_end)
        ax2.set_ylim(-0.02, 1.02)
        ax2.set_ylabel("P(speech)")
        ax2.legend(loc="upper right", fontsize=7)
        ax2.set_title("Silero VAD probability")

        # ── Panel 3: final (post-concatenation) waveform ─────────────────
        t_fin = np.arange(len(final)) / sr
        ax3.plot(t_fin, final, linewidth=0.3, color="#1f77b4")
        ax3.set_xlim(0, t_fin[-1] if len(final) else 1)
        ax3.set_ylim(-y_max_fin, y_max_fin)
        ax3.set_xlabel("seconds")
        ax3.set_title("Final (concatenated + comfort noise)")

        fig.tight_layout()

        if return_bytes:
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=120)
            buf.seek(0)
            png_bytes = buf.read()
            _plt.close(fig)
            return png_bytes

        assert path is not None
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(path), dpi=120)
        _plt.close(fig)
        logger.info("[DSP_DEBUG] Dumped %s", path.name)
        return None
    except Exception as exc:
        if not return_bytes and path:
            logger.info("[DSP_DEBUG] Failed to write %s: %s", path.name, exc)
        return None
