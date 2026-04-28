"""Unit tests for the VAD-planned chunking pipeline.

Tests cover the audio-free pieces (scorer, planner, mask helpers, audio
utilities).  The full ``preprocess_for_transcription`` integration is
exercised in the workbook + manual acceptance, since Silero classifies
synthetic noise inconsistently.
"""

import numpy as np
import pytest
from pydub import AudioSegment

from services.transcription.dsp.audio_utils import (
    estimate_encoded_size_mb,
    get_audio_mime_type,
)
from services.transcription.dsp.debug import DEBUG_DSP
from services.transcription.dsp.planner import (
    derive_silence_gaps, materialize_chunks, plan_chunks, _pressure_factor,
)
from services.transcription.dsp.scoring import (
    _depth_score, _duration_score, _restart_score, _stability_score,
    score_boundary,
)
from services.transcription.dsp.silence import _find_mask_runs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silent_audio(
    duration_ms: int = 5_000,
    sample_rate: int = 16_000,
    channels: int = 1,
) -> AudioSegment:
    num_samples = int(duration_ms * sample_rate / 1000) * channels
    raw = np.zeros(num_samples, dtype=np.int16)
    return AudioSegment(
        raw.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=channels,
    )


# ---------------------------------------------------------------------------
# _find_mask_runs
# ---------------------------------------------------------------------------

class TestFindMaskRuns:
    def test_empty(self):
        assert _find_mask_runs(np.array([], dtype=bool)) == []

    def test_single_run(self):
        mask = np.array([False, True, True, True, False], dtype=bool)
        assert _find_mask_runs(mask) == [(1, 4)]

    def test_multiple_runs(self):
        mask = np.array([True, True, False, True, False, True, True], dtype=bool)
        assert _find_mask_runs(mask) == [(0, 2), (3, 4), (5, 7)]


# ---------------------------------------------------------------------------
# Audio utilities
# ---------------------------------------------------------------------------

class TestGetAudioMimeType:
    def test_known_formats(self):
        assert get_audio_mime_type("test.mp3") == "audio/mpeg"
        assert get_audio_mime_type("test.wav") == "audio/wav"
        assert get_audio_mime_type("test.flac") == "audio/flac"
        assert get_audio_mime_type("test.webm") == "audio/webm"

    def test_unknown_format(self):
        assert get_audio_mime_type("test.xyz") == "audio/mpeg"


class TestEstimateEncodedSizeMb:
    def test_flac_smaller_than_wav(self):
        audio = _make_silent_audio(duration_ms=1000, sample_rate=16_000)
        assert (
            estimate_encoded_size_mb(audio, 'flac')
            < estimate_encoded_size_mb(audio, 'wav')
        )


# ---------------------------------------------------------------------------
# Scorer (pure, no audio)
# ---------------------------------------------------------------------------

class TestDurationScore:
    def test_at_target_is_half(self):
        assert _duration_score(500.0, 500.0) == pytest.approx(0.5)

    def test_above_target_higher(self):
        assert _duration_score(800.0, 500.0) > 0.5

    def test_below_target_lower(self):
        assert _duration_score(200.0, 500.0) < 0.5


class TestStabilityScore:
    def test_constant_is_one(self):
        probs = np.full(20, 0.05, dtype=np.float32)
        assert _stability_score(probs) == pytest.approx(1.0)

    def test_high_variance_low(self):
        probs = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0], dtype=np.float32)
        assert _stability_score(probs) < 0.05


class TestRestartScore:
    def test_steep_rise(self):
        probs = np.array([0.0, 0.3, 0.7, 1.0], dtype=np.float32)
        assert _restart_score(probs) == pytest.approx(1.0)

    def test_no_rise(self):
        probs = np.array([0.1, 0.1, 0.1, 0.1], dtype=np.float32)
        assert _restart_score(probs) == pytest.approx(0.0)

    def test_empty_returns_zero(self):
        assert _restart_score(np.zeros(0)) == 0.0


class TestDepthScore:
    def test_silent_high(self):
        probs = np.zeros(10, dtype=np.float32)
        assert _depth_score(probs) == pytest.approx(1.0)

    def test_loud_low(self):
        probs = np.ones(10, dtype=np.float32)
        assert _depth_score(probs) == pytest.approx(0.0)


class TestScoreBoundary:
    def test_great_silence_high_confidence(self):
        # 64 frames of solid silence (≈2 s) followed by a steep rise.
        n = 64
        gap_probs = np.zeros(n, dtype=np.float32)
        rise = np.linspace(0.0, 1.0, 8, dtype=np.float32)
        probs = np.concatenate([np.full(20, 0.9, dtype=np.float32),
                                gap_probs, rise,
                                np.full(20, 0.9, dtype=np.float32)])
        frame_ms = 32.0
        gap_start = 20 * frame_ms
        gap_end = (20 + n) * frame_ms
        score = score_boundary(gap_start, gap_end, probs, frame_ms)
        assert score.confidence > 0.7
        assert score.duration > 0.9 and score.depth > 0.9
        assert score.midpoint_ms == pytest.approx((gap_start + gap_end) / 2.0)

    def test_short_noisy_gap_low_confidence(self):
        n = 5  # 5 * 32 = 160 ms — well below the 500 ms target
        gap_probs = np.array([0.4, 0.6, 0.5, 0.7, 0.55], dtype=np.float32)
        probs = np.concatenate([np.full(10, 0.9, dtype=np.float32),
                                gap_probs,
                                np.full(10, 0.5, dtype=np.float32)])
        frame_ms = 32.0
        gap_start = 10 * frame_ms
        gap_end = 15 * frame_ms
        score = score_boundary(gap_start, gap_end, probs, frame_ms)
        assert score.confidence < 0.5


# ---------------------------------------------------------------------------
# Planner (pure, no audio)
# ---------------------------------------------------------------------------

class TestDeriveSilenceGaps:
    def test_head_tail_only(self):
        assert derive_silence_gaps([], 1000.0) == [(0.0, 1000.0)]

    def test_with_speech(self):
        gaps = derive_silence_gaps([(200.0, 400.0), (700.0, 800.0)], 1000.0)
        assert gaps == [(0.0, 200.0), (400.0, 700.0), (800.0, 1000.0)]

    def test_zero_length_dropped(self):
        gaps = derive_silence_gaps([(0.0, 200.0)], 200.0)
        assert gaps == []


class TestPressureFactor:
    def test_at_min_is_one(self):
        assert _pressure_factor(20_000, 20_000, 40_000) == pytest.approx(1.0)

    def test_at_max_is_floor(self):
        from services.transcription.dsp.planner import PRESSURE_FLOOR
        assert _pressure_factor(40_000, 20_000, 40_000) == pytest.approx(PRESSURE_FLOOR, abs=1e-3)

    def test_below_min_clamps(self):
        assert _pressure_factor(0, 20_000, 40_000) == pytest.approx(1.0)


class TestPlanChunks:
    def test_short_audio_single_chunk(self):
        plan = plan_chunks(
            speech_regions_ms=[(0.0, 5_000.0)],
            total_ms=10_000.0,
            probs=np.zeros(0, dtype=np.float32),
            frame_ms=32.0,
        )
        assert len(plan) == 1
        assert plan[0].boundary_type == "end_of_audio"
        assert plan[0].start_ms == 0.0
        assert plan[0].end_ms == 10_000.0

    def test_long_audio_no_silence_forces_split(self):
        # No speech regions ⇒ single huge silence gap covering the whole file.
        # The midpoint of that gap is at 30s, which lies inside [20s, 40s].
        # The huge gap is a fantastic candidate ⇒ split is "natural".
        plan = plan_chunks(
            speech_regions_ms=[],
            total_ms=120_000.0,
            probs=np.zeros(int(120_000 / 32.0) + 1, dtype=np.float32),
            frame_ms=32.0,
            min_chunk_ms=20_000,
            max_chunk_ms=40_000,
        )
        # Should produce at least 2 chunks.
        assert len(plan) >= 2
        # All splits except last should have a chosen_boundary or be "forced".
        for entry in plan[:-1]:
            assert entry.boundary_type in {"natural", "forced"}
        assert plan[-1].boundary_type == "end_of_audio"
        # Logical contiguity.
        for a, b in zip(plan, plan[1:]):
            assert a.end_ms == b.start_ms

    def test_solid_speech_no_silence_forces_hard_cut(self):
        # Solid speech over the entire 60 s — no gap exists in [20, 40].
        # Planner must hard-cut at max_chunk_ms.
        plan = plan_chunks(
            speech_regions_ms=[(0.0, 60_000.0)],
            total_ms=60_000.0,
            probs=np.full(int(60_000 / 32.0) + 1, 0.9, dtype=np.float32),
            frame_ms=32.0,
            min_chunk_ms=20_000,
            max_chunk_ms=40_000,
        )
        assert plan[0].boundary_type == "forced"
        assert plan[0].end_ms == pytest.approx(40_000.0)

    def test_natural_silence_chosen(self):
        # Speech 0–25 s, silence 25–26 s, speech 26–50 s.
        # The 1-second silence sits comfortably inside [20, 40] s.
        n_frames = int(50_000 / 32.0) + 1
        probs = np.full(n_frames, 0.9, dtype=np.float32)
        # Drive the silence frames near zero so it scores well.
        gap_start_frame = int(25_000 / 32.0)
        gap_end_frame = int(26_000 / 32.0)
        probs[gap_start_frame:gap_end_frame] = 0.05
        plan = plan_chunks(
            speech_regions_ms=[(0.0, 25_000.0), (26_000.0, 50_000.0)],
            total_ms=50_000.0, probs=probs, frame_ms=32.0,
            min_chunk_ms=20_000,
            max_chunk_ms=40_000,
        )
        # Natural or forced — either way the split should land in the silence
        # midpoint (≈25.5s) since it's the only candidate inside [20, 40]s.
        assert plan[0].boundary_type in {"natural", "forced"}
        # Split should be the midpoint of the silence gap (25.5 s).
        assert plan[0].end_ms == pytest.approx(25_500.0, abs=50.0)


# ---------------------------------------------------------------------------
# Materialise
# ---------------------------------------------------------------------------

class TestMaterializeChunks:
    def test_overlap_clamped_to_zero_for_first_chunk(self):
        from services.transcription.models import ChunkPlanEntry
        audio = _make_silent_audio(duration_ms=10_000)
        plan = [
            ChunkPlanEntry(0, 0.0, 5_000.0, "natural"),
            ChunkPlanEntry(1, 5_000.0, 10_000.0, "end_of_audio"),
        ]
        chunks = materialize_chunks(audio, plan, overlap_ms=2_000)
        assert chunks[0].actual_start_ms == 0.0
        assert chunks[1].actual_start_ms == 3_000.0
        assert chunks[1].logical_start_ms == 5_000.0

    def test_no_excision_when_speech_regions_omitted(self):
        from services.transcription.models import ChunkPlanEntry
        audio = _make_silent_audio(duration_ms=10_000)
        plan = [ChunkPlanEntry(0, 0.0, 10_000.0, "end_of_audio")]
        chunks = materialize_chunks(audio, plan, overlap_ms=0)
        assert chunks[0].excision_map is None
        assert len(chunks[0].audio_segment) == 10_000

    def test_excision_collapses_long_silence(self):
        from services.transcription.models import ChunkPlanEntry
        audio = _make_silent_audio(duration_ms=10_000)
        plan = [ChunkPlanEntry(0, 0.0, 10_000.0, "end_of_audio")]
        # Speech regions: 1-2s and 8-9s. Pad=200ms collapses the 6s middle silence.
        # This is the last (only) chunk so trailing silence is preserved
        # all the way to the end of the chunk window (10s).
        chunks = materialize_chunks(
            audio, plan, overlap_ms=0,
            speech_regions_ms=[(1_000.0, 2_000.0), (8_000.0, 9_000.0)],
            excision_pad_ms=200,
        )
        em = chunks[0].excision_map
        assert em is not None
        # Region1 = 0.8-2.2s (1.4s); region2 = 7.8-10.0s (extended to chunk end -> 2.2s).
        assert len(chunks[0].audio_segment) == pytest.approx(3_600, abs=10)
        assert em.original_duration_ms == 10_000
        # Mapping: excised 1.5s = 1.4s of region1 + 0.1s into region2 -> 7.9s
        assert em.to_original_time_ms(1_500.0) == pytest.approx(7_900.0, abs=10)

    def test_excision_disabled_when_pad_zero(self):
        from services.transcription.models import ChunkPlanEntry
        audio = _make_silent_audio(duration_ms=5_000)
        plan = [ChunkPlanEntry(0, 0.0, 5_000.0, "end_of_audio")]
        chunks = materialize_chunks(
            audio, plan, overlap_ms=0,
            speech_regions_ms=[(1_000.0, 2_000.0)],
            excision_pad_ms=0,
        )
        assert chunks[0].excision_map is None
        assert len(chunks[0].audio_segment) == 5_000

    def test_final_chunk_preserves_trailing_silence(self):
        """Last chunk's final keep-run extends to the chunk end, preserving
        every sample after the final speech region as the EOS cue.
        """
        from services.transcription.models import ChunkPlanEntry
        audio = _make_silent_audio(duration_ms=10_000)
        # Two chunks: 0-5s and 5-10s.  Final speech ends at 6s; the last
        # chunk's final keep-run must extend to 10s (chunk end).
        plan = [
            ChunkPlanEntry(0, 0.0, 5_000.0, "natural"),
            ChunkPlanEntry(1, 5_000.0, 10_000.0, "end_of_audio"),
        ]
        chunks = materialize_chunks(
            audio, plan, overlap_ms=0,
            speech_regions_ms=[(1_000.0, 2_000.0), (5_500.0, 6_000.0)],
            excision_pad_ms=200,
        )
        last = chunks[-1]
        assert last.excision_map is not None
        # Final keep-run = (5500-200)-5000 .. 5000 (chunk end) = 300..5000 -> 4700ms
        last_run = last.excision_map.keep_regions_ms[-1]
        assert last_run[1] - last_run[0] == pytest.approx(4_700, abs=10)
        # Non-final chunk uses the normal 200ms pad on its right edge.
        first_run = chunks[0].excision_map.keep_regions_ms[-1]
        assert first_run[1] - first_run[0] == pytest.approx(1_400, abs=10)


# ---------------------------------------------------------------------------
# Seam dedup (case / punctuation tolerant)
# ---------------------------------------------------------------------------

class TestSeamDedup:
    def test_case_mismatch_dedup(self):
        from services.transcription.overlap import deduplicate_seam
        prev = "Just checking to see how this"
        new = " See how this interprets my natural flow of speech."
        assert deduplicate_seam(prev, new) == "interprets my natural flow of speech."

    def test_no_overlap_returns_input(self):
        from services.transcription.overlap import deduplicate_seam
        assert deduplicate_seam("Hello world.", " Goodbye now.") == " Goodbye now."

    def test_punctuation_drift_still_matches(self):
        from services.transcription.overlap import deduplicate_seam
        prev = "okay, so the plan is"
        new = "So the plan is to ship today."
        assert deduplicate_seam(prev, new) == "to ship today."


# ---------------------------------------------------------------------------
# DEBUG_DSP default
# ---------------------------------------------------------------------------

class TestDebugDsp:
    def test_debug_defaults_false(self):
        import os
        if os.environ.get("DSP_DEBUG", "").lower() not in ("1", "true", "yes"):
            assert DEBUG_DSP is False
