"""DSP pipeline: limit → compress → VAD silence detection → excise → noise floor.

Production-grade single-pipeline preprocessor for gpt-4o-transcribe.

Why each stage exists
---------------------
1. **Transient limiter** — Brick-wall ceiling with lookahead prevents
   clipping artifacts that confuse the ASR encoder into hallucinating
   phonemes from distortion harmonics.

2. **Dynamic range compressor** — Tames loud-after-quiet transitions.
   gpt-4o-transcribe interprets a sudden energy jump after a quiet
   passage as a new utterance boundary, emitting <|endoftext|>.
   Compression smooths the envelope so energy transitions are gradual.

3. **VAD silence detection** — WebRTC VAD classifies frames by spectral
   characteristics (not just energy), so transient spikes like mic bumps
   or taps don't fool it.  Only silence regions longer than
   *min_silence_ms* are flagged.

4. **Silence excision** — Physically removes flagged silence (with
   grace/tail context preserved) so the encoder never sees a long
   zero-energy span.  gpt-4o-transcribe emits <|endoftext|> on gaps
   >~1.5 s; excision prevents this without injecting artificial noise.

5. **Flat noise floor** — Adds very low-level white noise across the
   entire output to prevent true digital silence, which can trigger
   codec artefacts and ASR end-of-stream heuristics in edge cases.

Timestamp remapping
-------------------
The ``ExcisionMap`` returned alongside the processed audio translates
timestamps from excised-audio coordinates back to original-audio
coordinates, so diarisation and segment timings remain accurate.
"""

import base64
import re
import time
from pathlib import Path

import numpy as np
from pydub import AudioSegment

from framework.logger import get_logger
from services.transcription.models import ExcisionMap, PreprocessResult

from services.transcription.dsp.compressor import limit_transients, compress_dynamic_range
from services.transcription.dsp.silence import (
    _find_mask_runs,
    _shape_injection_mask,
    _detect_silence_vad,
)
from services.transcription.dsp.debug import (
    DEBUG_DSP,
    _dump_debug_audio,
    _plot_excision_overlay,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Validated pipeline defaults
# ---------------------------------------------------------------------------
DEFAULT_COMPRESSOR_RATIO = 3.0
DEFAULT_COMPRESSOR_THRESHOLD_DB = -30.0
DEFAULT_COMPRESSOR_ATTACK_MS = 10.0
DEFAULT_COMPRESSOR_RELEASE_MS = 100.0
DEFAULT_MAKEUP_TARGET_DB = -16.0
DEFAULT_LIMITER_CEILING_DB = -6.0
DEFAULT_VAD_AGGRESSIVENESS = 2
DEFAULT_MIN_SILENCE_MS = 1000
DEFAULT_MIN_GAP_MS = 400
DEFAULT_GRACE_MS = 150
DEFAULT_TAIL_MS = 150
DEFAULT_NOISE_LEVEL_DB = -58.0


# ---------------------------------------------------------------------------
# Main pipeline entry point
# ---------------------------------------------------------------------------

def preprocess_for_transcription(
    audio_segment: AudioSegment,
    min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
    debug_tag: str | None = None,
    return_waveform_overlay: bool = False,
) -> PreprocessResult:
    """Preprocess audio for gpt-4o-transcribe: limit → compress → excise → noise floor.

    This is the single production DSP pipeline.  It produces an
    ``AudioSegment`` that is safe for single-shot transcription (no long
    silences that trigger <|endoftext|>) plus an ``ExcisionMap`` for
    remapping timestamps back to the original recording.

    Args:
        audio_segment: Input audio (any sample rate, any channel count).
        min_silence_ms: Minimum silence duration in ms to trigger excision.
            Shorter silences are left intact.
        debug_tag: Optional tag for debug artifact filenames (used when
            ``DSP_DEBUG=1`` is set in the environment).
        return_waveform_overlay: If True, include a base64-encoded PNG
            waveform overlay in the result.

    Returns:
        ``PreprocessResult`` containing the processed audio, an
        ``ExcisionMap`` for timestamp remapping, and an optional
        waveform overlay PNG.
    """
    t0 = time.perf_counter()
    sr = audio_segment.frame_rate
    channels = audio_segment.channels

    logger.info(
        "pipeline: min_silence=%dms audio=%dms sr=%d ch=%d",
        min_silence_ms, len(audio_segment), sr, channels,
    )

    # ── Convert to numpy ─────────────────────────────────────────────────
    t_c = time.perf_counter()
    raw_i16 = np.array(audio_segment.get_array_of_samples(), dtype=np.int16)
    num_frames = len(raw_i16) // channels
    samples_2d = raw_i16.reshape((num_frames, channels))
    mono = samples_2d.mean(axis=1).astype(np.float32) / np.float32(32768.0)
    logger.info(
        "[timing] stage=pipeline.to_numpy duration_ms=%d",
        int((time.perf_counter() - t_c) * 1000),
    )

    # ── Debug setup ──────────────────────────────────────────────────────
    _dbg = None
    if DEBUG_DSP:
        ts = time.strftime("%Y%m%d_%H%M%S")
        tag = re.sub(r"[^\w]+", "_", Path(debug_tag).stem).strip("_") if debug_tag else ""
        _dbg = Path(".") / "debug" / (f"{ts}_{tag}" if tag else ts)
        _dbg.mkdir(parents=True, exist_ok=True)
        logger.info("[DSP_DEBUG] Debug artifacts → %s", _dbg)
        _dump_debug_audio(mono, sr, _dbg / "01_raw.wav")

    # ── Stage 1: Transient limiter ───────────────────────────────────────
    t_c = time.perf_counter()
    original_peak = float(np.max(np.abs(mono)))
    ceiling_lin = 10.0 ** (DEFAULT_LIMITER_CEILING_DB / 20.0)
    n_limited = int(np.sum(np.abs(mono) > ceiling_lin))

    limited_mono, limiter_gain = limit_transients(
        mono, sr, ceiling_db=DEFAULT_LIMITER_CEILING_DB,
    )

    limited_peak = float(np.max(np.abs(limited_mono)))
    pct = n_limited * 100.0 / num_frames if num_frames else 0.0
    logger.info(
        "Limiter: %d samples exceeded ceiling (%.1f%%), "
        "peak reduced from %.3f to %.3f",
        n_limited, pct, original_peak, limited_peak,
    )
    logger.info(
        "[timing] stage=pipeline.limiter duration_ms=%d",
        int((time.perf_counter() - t_c) * 1000),
    )

    # ── Stage 2: Dynamic range compression ───────────────────────────────
    t_c = time.perf_counter()
    compressed_mono, compressor_gain = compress_dynamic_range(
        limited_mono, sr,
        ratio=DEFAULT_COMPRESSOR_RATIO,
        threshold_db=DEFAULT_COMPRESSOR_THRESHOLD_DB,
        attack_ms=DEFAULT_COMPRESSOR_ATTACK_MS,
        release_ms=DEFAULT_COMPRESSOR_RELEASE_MS,
        makeup_target_db=DEFAULT_MAKEUP_TARGET_DB,
    )
    logger.info(
        "[timing] stage=pipeline.compress duration_ms=%d",
        int((time.perf_counter() - t_c) * 1000),
    )

    if _dbg:
        _dump_debug_audio(compressed_mono, sr, _dbg / "02_compressed.wav")

    # ── Stage 3: VAD silence detection (on compressed mono) ──────────────
    silence_mask = _detect_silence_vad(
        compressed_mono, sr,
        aggressiveness=DEFAULT_VAD_AGGRESSIVENESS,
        min_silence_ms=min_silence_ms,
        min_gap_ms=DEFAULT_MIN_GAP_MS,
    )

    # ── Stage 4: Silence excision ────────────────────────────────────────
    # Compose limiter and compressor gains and apply once to all channels
    total_gain = limiter_gain * compressor_gain
    out_2d = samples_2d.astype(np.float32) / np.float32(32768.0)
    for ch in range(channels):
        out_2d[:, ch] *= total_gain
    out_2d = np.clip(out_2d, -1.0, 1.0)
    comp_i16 = (out_2d * np.float32(32768.0)).astype(np.int16)

    silence_processed = False
    inj_mask = np.zeros(num_frames, dtype=bool)
    excision_keep_runs: list[tuple[int, int]] | None = None

    if int(np.sum(silence_mask)) > 0:
        t_c = time.perf_counter()
        # Shape the mask with grace/tail carving.  Since VAD produces a
        # single clean mask, fine_mask == coarse_mask.
        inj_mask = _shape_injection_mask(
            silence_mask, silence_mask, sr,
            grace_ms=DEFAULT_GRACE_MS,
            tail_ms=DEFAULT_TAIL_MS,
        )
        inj_count = int(np.sum(inj_mask))
        if inj_count > 0:
            keep_mask = ~inj_mask
            keep_runs = _find_mask_runs(keep_mask)
            excision_keep_runs = keep_runs
            segments = [comp_i16[s:e] for s, e in keep_runs]
            if segments:
                comp_i16 = np.concatenate(segments, axis=0)
                silence_processed = True
            inj_runs = _find_mask_runs(inj_mask)
            removed_ms = inj_count * 1000.0 / sr
            logger.info(
                "Excised %d silence region(s): removed %.0fms, "
                "duration %.0fms → %.0fms",
                len(inj_runs), removed_ms,
                num_frames * 1000.0 / sr,
                len(comp_i16) * 1000.0 / sr,
            )
        else:
            logger.info("Silence detected but within grace/tail — no excision")
        logger.info(
            "[timing] stage=pipeline.excise duration_ms=%d",
            int((time.perf_counter() - t_c) * 1000),
        )
    else:
        logger.info("No silence detected — skipping excision")

    if _dbg and silence_processed:
        proc_mono = comp_i16.mean(axis=1).astype(np.float32) / np.float32(32768.0)
        _dump_debug_audio(proc_mono, sr, _dbg / "03_excised.wav")

    # ── Stage 5: Flat noise floor ────────────────────────────────────────
    t_c = time.perf_counter()
    n_out = len(comp_i16)
    noise_amp = np.float32(10.0 ** (DEFAULT_NOISE_LEVEL_DB / 20.0))
    noise = np.random.randn(n_out).astype(np.float32) * noise_amp

    final_2d = comp_i16.astype(np.float32) / np.float32(32768.0)
    for ch in range(channels):
        final_2d[:, ch] += noise
    final_2d = np.clip(final_2d, -1.0, 1.0)
    final_i16 = (final_2d * np.float32(32768.0)).astype(np.int16).flatten()
    logger.info(
        "[timing] stage=pipeline.noise_floor duration_ms=%d",
        int((time.perf_counter() - t_c) * 1000),
    )

    # ── Build ExcisionMap ────────────────────────────────────────────────
    if excision_keep_runs is not None:
        excision_map = ExcisionMap.from_keep_runs(
            excision_keep_runs, sr, num_frames,
        )
        logger.info(
            "ExcisionMap: %d keep-regions, original=%.0fms excised=%.0fms",
            len(excision_keep_runs),
            excision_map.original_duration_ms,
            excision_map.excised_duration_ms,
        )
    else:
        excision_map = ExcisionMap.identity(num_frames * 1000.0 / sr)

    # ── Build output AudioSegment ────────────────────────────────────────
    result = AudioSegment(
        final_i16.tobytes(),
        frame_rate=sr,
        sample_width=audio_segment.sample_width,
        channels=channels,
    )
    logger.info(
        "[timing] stage=pipeline.total duration_ms=%d audio_ms=%d sr=%d ch=%d",
        int((time.perf_counter() - t0) * 1000), len(audio_segment), sr, channels,
    )

    # ── Debug: final + overlay ───────────────────────────────────────────
    waveform_overlay_b64 = None
    final_mono = final_2d.mean(axis=1).astype(np.float32)

    if _dbg:
        _dump_debug_audio(final_mono, sr, _dbg / "05_final.wav")
        _plot_excision_overlay(
            mono, final_mono, sr, silence_mask, inj_mask,
            _dbg / "waveform_overlay.png",
        )

    if return_waveform_overlay:
        overlay_bytes = _plot_excision_overlay(
            mono, final_mono, sr, silence_mask, inj_mask,
            path=None, return_bytes=True,
        )
        if overlay_bytes:
            waveform_overlay_b64 = base64.b64encode(overlay_bytes).decode('utf-8')

    return PreprocessResult(
        audio=result,
        excision_map=excision_map,
        waveform_overlay=waveform_overlay_b64,
    )
