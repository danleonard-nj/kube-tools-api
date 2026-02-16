"""Debug helpers for the DSP pipeline.

Controlled by the ``DSP_DEBUG`` environment variable.  When enabled,
intermediate audio stages and waveform overlay plots are written to disk
for offline inspection.  Disabled by default in production.
"""

import io
import os
from pathlib import Path

import numpy as np

from framework.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Debug flag — disabled by default, enable via environment variable
# ---------------------------------------------------------------------------
DEBUG_DSP = os.environ.get("DSP_DEBUG", "").lower() in ("1", "true", "yes")

# Conditional imports for debug-only dependencies
try:
    import soundfile as _sf
    _HAS_SOUNDFILE = True
except ImportError:
    _sf = None
    _HAS_SOUNDFILE = False

try:
    import matplotlib
    matplotlib.use("Agg")  # non-interactive backend, safe for headless/async
    import matplotlib.pyplot as _plt
    _HAS_MATPLOTLIB = True
except ImportError:
    _plt = None
    _HAS_MATPLOTLIB = False


def _dump_debug_audio(samples: np.ndarray, sr: int, path: Path) -> None:
    """Write mono float32 samples to a WAV file via soundfile.

    Logs size, duration, and sample rate on success.  If soundfile is
    unavailable, returns silently.
    """
    if not _HAS_SOUNDFILE:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _sf.write(str(path), samples, sr, subtype='FLOAT')
        size_bytes = path.stat().st_size
        duration_ms = int(len(samples) * 1000 / sr)
        logger.info(
            "[DSP_DEBUG] Dumped %s (size=%d, duration_ms=%d, sr=%d)",
            path.name, size_bytes, duration_ms, sr,
        )
    except Exception as exc:
        logger.info("[DSP_DEBUG] Failed to write %s: %s", path.name, exc)


def _plot_excision_overlay(
    raw: np.ndarray,
    final: np.ndarray,
    sr: int,
    silence_mask: np.ndarray,
    inj_mask: np.ndarray,
    path: Path | None,
    mode_label: str = "excision",
    return_bytes: bool = False,
) -> bytes | None:
    """Two-panel plot: raw with silence regions vs processed final.

    Top panel shows the raw waveform with coarse silence (red) and
    excised regions (blue) shaded.  Bottom panel shows the final output
    after excision and noise floor.

    Args:
        raw: Pre-processing mono samples.
        final: Post-processing mono samples (may be shorter after excision).
        sr: Sample rate in Hz.
        silence_mask: Boolean mask of detected silence regions.
        inj_mask: Boolean mask of excised/injected regions.
        path: Output file path, or None when *return_bytes* is True.
        mode_label: Label for the bottom panel title.
        return_bytes: If True, returns PNG bytes instead of saving to disk.

    Returns:
        PNG bytes when *return_bytes* is True, None otherwise.
    """
    if not _HAS_MATPLOTLIB:
        return None
    try:
        fig, (ax1, ax2) = _plt.subplots(2, 1, figsize=(16, 6))
        t_raw = np.arange(len(raw)) / sr
        y_max = float(max(np.abs(raw).max(), np.abs(final).max(), 1e-6)) * 1.05

        ax1.plot(t_raw, raw, linewidth=0.3, color="gray", label="raw")
        ax1.fill_between(
            t_raw, -y_max, y_max,
            where=silence_mask[:len(raw)].astype(bool),
            color="red", alpha=0.12, label="coarse silence", step="mid",
        )
        ax1.fill_between(
            t_raw, -y_max, y_max,
            where=inj_mask[:len(raw)].astype(bool),
            color="blue", alpha=0.15, label="excised", step="mid",
        )
        ax1.set_xlim(0, t_raw[-1] if len(raw) else 1)
        ax1.set_ylim(-y_max, y_max)
        ax1.set_title("Raw + silence regions")
        ax1.legend(loc="upper right", fontsize=7)

        t_fin = np.arange(len(final)) / sr
        ax2.plot(t_fin, final, linewidth=0.3, color="#1f77b4")
        ax2.set_xlim(0, t_fin[-1] if len(final) else 1)
        ax2.set_ylim(-y_max, y_max)
        ax2.set_xlabel("seconds")
        ax2.set_title(f"After {mode_label} + noise floor")

        fig.tight_layout()

        if return_bytes:
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=120)
            buf.seek(0)
            png_bytes = buf.read()
            _plt.close(fig)
            return png_bytes
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(str(path), dpi=120)
            _plt.close(fig)
            logger.info("[DSP_DEBUG] Dumped %s", path.name)
            return None
    except Exception as exc:
        if not return_bytes and path:
            logger.info("[DSP_DEBUG] Failed to write %s: %s", path.name, exc)
        return None
