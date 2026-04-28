"""Workbench overlay for the chunk-planning pipeline.

Three panels (shared time axis on 1 + 2):

1. Raw waveform.  Chunks are shaded in alternating tints; boundaries are
   drawn as vertical lines and annotated with confidence + per-feature
   breakdown.  Forced boundaries are drawn in red.  When ``chunks`` is
   provided, intra-chunk regions that the per-chunk excision dropped are
   striped in red — so you can see exactly what the encoder will *not*
   receive.
2. Silero P(speech) trace with the hysteresis ``p_hi``/``p_lo`` lines.
   Green dots mark winning candidate midpoints; gray dots mark losers.
3. Concatenated waveform of the (possibly excised) chunks back-to-back,
   with inter-chunk boundaries marked.  Title shows the excision savings.

Followed by a Markdown table: chunk_index, start_ms, end_ms, duration_ms,
boundary_type, confidence.

Renders to disk (PNG + ``.md``) and/or returns PNG bytes.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Optional

import numpy as np

from framework.logger import get_logger
from services.transcription.models import AudioChunk, ChunkPlanEntry

logger = get_logger(__name__)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    _HAS_MATPLOTLIB = True
except ImportError:
    _plt = None
    _HAS_MATPLOTLIB = False


_CHUNK_TINTS = ("#e8f0ff", "#fff0e8")

# Cap render resolution; keeps matplotlib peak memory bounded regardless
# of input length (1.6 s @ 16 kHz = 25k pts; full 16 MP RGBA fig ≈ 60 MB).
_MAX_PLOT_POINTS = 12_000


def _decimate(samples: np.ndarray, sr: int, max_points: int = _MAX_PLOT_POINTS):
    """Down-sample by integer stride for plotting.

    Returns ``(t_seconds, decimated_samples, effective_sr)``.  Avoids
    holding ``samples * 8`` bytes worth of x-axis in matplotlib.
    """
    n = len(samples)
    if n <= max_points or n == 0:
        return np.arange(n) / max(sr, 1), samples, sr
    stride = (n + max_points - 1) // max_points
    decimated = samples[::stride]
    eff_sr = sr / stride
    return np.arange(len(decimated)) / max(eff_sr, 1e-6), decimated, eff_sr


def _annotate_boundary(ax, x_sec: float, y_top: float, entry: ChunkPlanEntry) -> None:
    bs = entry.chosen_boundary
    color = "red" if entry.boundary_type == "forced" else "navy"
    ax.axvline(x_sec, color=color, linewidth=0.9, alpha=0.85)
    if bs is None:
        label = f"{entry.boundary_type}\n@{int(entry.end_ms)}ms"
    else:
        label = (
            f"conf={bs.confidence:.2f}\n"
            f"(dur={bs.duration:.2f}, stab={bs.stability:.2f},\n"
            f" rise={bs.restart_strength:.2f}, depth={bs.depth:.2f})"
        )
    ax.text(
        x_sec, y_top * 0.92, label,
        ha="center", va="top", fontsize=7, color=color,
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=color, alpha=0.75),
    )


def _chunk_audio_to_float(chunk_audio) -> np.ndarray:
    """Convert a pydub AudioSegment back to mono float32 in [-1, 1]."""
    raw = np.array(chunk_audio.get_array_of_samples(), dtype=np.int16)
    if chunk_audio.channels > 1:
        raw = raw.reshape((-1, chunk_audio.channels)).mean(axis=1).astype(np.int16)
    return raw.astype(np.float32) / np.float32(32768.0)


def _shade_dropped_regions(ax, chunk: AudioChunk, y_max: float) -> None:
    """Stripe regions inside the chunk window that excision will drop."""
    em = chunk.excision_map
    if em is None or em.is_identity:
        return
    base_sec = chunk.actual_start_ms / 1000.0
    chunk_end_sec = chunk.actual_end_ms / 1000.0
    cursor = 0.0
    for ks, ke in em.keep_regions_ms:
        if ks > cursor:
            ax.axvspan(
                base_sec + cursor / 1000.0, base_sec + ks / 1000.0,
                facecolor="red", alpha=0.18, hatch="///",
                edgecolor="red", linewidth=0.0, zorder=1,
            )
        cursor = ke
    chunk_local_end = (chunk_end_sec - base_sec) * 1000.0
    if cursor < chunk_local_end:
        ax.axvspan(
            base_sec + cursor / 1000.0, chunk_end_sec,
            facecolor="red", alpha=0.18, hatch="///",
            edgecolor="red", linewidth=0.0, zorder=1,
        )


def render_chunk_plan_overlay(
    raw: np.ndarray,
    sr: int,
    probs: np.ndarray,
    frame_ms: float,
    plan: List[ChunkPlanEntry],
    p_hi: float,
    p_lo: float,
    path: Optional[Path] = None,
    return_bytes: bool = False,
    chunks: Optional[List[AudioChunk]] = None,
) -> Optional[bytes]:
    """Render the 3-panel chunk-plan overlay.

    Either writes ``path`` (PNG) or returns PNG bytes when
    ``return_bytes=True``.  Returns ``None`` when matplotlib is missing
    or rendering fails.

    When ``chunks`` is supplied, panel 1 shades the regions excision will
    drop (red striping) and panel 3 plots the actual concatenated
    excised audio with the savings reported in the title.
    """
    if not _HAS_MATPLOTLIB:
        return None
    try:
        fig, (ax1, ax2, ax3) = _plt.subplots(3, 1, figsize=(16, 9))
        t_raw, raw_plot, _ = _decimate(raw, sr)
        x_end = t_raw[-1] if len(raw_plot) else 1.0
        y_max_raw = float(max(np.abs(raw_plot).max(), 1e-6)) * 1.05 if len(raw_plot) else 1.0

        # ── Panel 1: raw waveform + chunk shading + boundary annotations ──
        ax1.plot(t_raw, raw_plot, linewidth=0.3, color="gray")
        for i, entry in enumerate(plan):
            ax1.axvspan(
                entry.start_ms / 1000.0, entry.end_ms / 1000.0,
                color=_CHUNK_TINTS[i % 2], alpha=0.55, zorder=0,
            )
        if chunks:
            for ch in chunks:
                _shade_dropped_regions(ax1, ch, y_max_raw)
        for entry in plan[:-1]:  # last boundary is end_of_audio, no annotation
            _annotate_boundary(ax1, entry.end_ms / 1000.0, y_max_raw, entry)
        ax1.set_xlim(0, x_end)
        ax1.set_ylim(-y_max_raw, y_max_raw)
        title1 = f"Raw waveform — {len(plan)} chunks"
        if chunks:
            title1 += " (red stripes = excised silence)"
        ax1.set_title(title1)

        # ── Panel 2: probability + hysteresis + candidate dots ────────────
        t_probs = (np.arange(len(probs)) * frame_ms + frame_ms / 2.0) / 1000.0
        ax2.plot(t_probs, probs, linewidth=0.6, color="#222")
        ax2.axhline(p_hi, linestyle="--", linewidth=0.8, color="green", label=f"p_hi={p_hi}")
        ax2.axhline(p_lo, linestyle="--", linewidth=0.8, color="red", label=f"p_lo={p_lo}")

        for entry in plan:
            if entry.chosen_boundary is not None:
                ax2.scatter(
                    entry.chosen_boundary.midpoint_ms / 1000.0,
                    entry.chosen_boundary.confidence,
                    color="green", s=22, zorder=3,
                )
            for c in entry.rejected_candidates:
                ax2.scatter(
                    c.midpoint_ms / 1000.0, c.confidence,
                    color="gray", s=12, alpha=0.6, zorder=2,
                )
        ax2.set_xlim(0, x_end)
        ax2.set_ylim(-0.02, 1.02)
        ax2.set_ylabel("P(speech)")
        ax2.legend(loc="upper right", fontsize=7)
        ax2.set_title("Silero VAD — green=chosen, gray=rejected")

        # ── Panel 3: concat of (possibly excised) chunks ──────────────────
        if chunks:
            cat_segments = [_chunk_audio_to_float(c.audio_segment) for c in chunks]
            concat = np.concatenate(cat_segments) if cat_segments else np.zeros(0, dtype=np.float32)
            del cat_segments
            _, concat_plot, _ = _decimate(concat, sr)
            cat_y_max = float(max(np.abs(concat_plot).max(), 1e-6)) * 1.05 if len(concat_plot) else 1.0
            # Panel-3 time should follow chunk durations (AudioSegment ms),
            # not the raw/VAD sample rate used by panel 1/2.
            excised_sec = sum(len(c.audio_segment) for c in chunks) / 1000.0
            if len(concat_plot) > 0:
                t_cat = np.linspace(0.0, excised_sec, num=len(concat_plot), endpoint=False)
            else:
                t_cat = np.zeros(0, dtype=np.float32)
            ax3.plot(t_cat, concat_plot, linewidth=0.3, color="#1f77b4")
            cum_sec = 0.0
            for c in chunks[:-1]:
                cum_sec += len(c.audio_segment) / 1000.0
                ax3.axvline(cum_sec, color="black", linewidth=0.6, alpha=0.7)
            raw_sec = sum((c.actual_end_ms - c.actual_start_ms) for c in chunks) / 1000.0
            saved_pct = (1.0 - excised_sec / raw_sec) * 100.0 if raw_sec > 0 else 0.0
            ax3.set_xlim(0, max(excised_sec, 0.1))
            ax3.set_ylim(-cat_y_max, cat_y_max)
            ax3.set_title(
                f"Excised concat — {excised_sec:.2f}s of {raw_sec:.2f}s "
                f"({saved_pct:.1f}% silence dropped)"
            )
            del concat, concat_plot
        else:
            ax3.plot(t_raw, raw_plot, linewidth=0.3, color="#1f77b4")
            for entry in plan[:-1]:
                ax3.axvline(entry.end_ms / 1000.0, color="black", linewidth=0.6, alpha=0.7)
            ax3.set_xlim(0, x_end)
            ax3.set_ylim(-y_max_raw, y_max_raw)
            ax3.set_title("Concatenated reference (chunk boundaries marked)")
        ax3.set_xlabel("seconds")

        fig.tight_layout()

        if return_bytes:
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=90)
            buf.seek(0)
            data = buf.read()
            _plt.close(fig)
            return data

        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(str(path), dpi=90)
        _plt.close(fig)
        return None
    except Exception as exc:
        logger.info("[overlay] failed: %s", exc)
        return None


def render_chunk_plan_table(plan: List[ChunkPlanEntry]) -> str:
    """Markdown table for printing/logging alongside the overlay."""
    rows = ["| chunk | start_ms | end_ms | dur_ms | type | confidence |",
            "|------:|---------:|-------:|-------:|:-----|-----------:|"]
    for e in plan:
        conf = f"{e.chosen_boundary.confidence:.3f}" if e.chosen_boundary else "—"
        rows.append(
            f"| {e.chunk_index} | {int(e.start_ms)} | {int(e.end_ms)} | "
            f"{int(e.end_ms - e.start_ms)} | {e.boundary_type} | {conf} |"
        )
    return "\n".join(rows)
