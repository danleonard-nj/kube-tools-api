"""Unit tests for the silence-budgeting preprocessing pipeline.

Tests validate:
- ``_find_mask_runs``: contiguous True-run finder
- ``hysteresis_speech_regions``: hysteresis on a synthetic probability stream
- ``_budget_keep_regions``: capped vs. intact gap behaviour
- ``get_audio_mime_type``, ``estimate_encoded_size_mb``, ``is_single_shot_safe``
- ``preprocess_for_transcription``: contract smoke test

The full pipeline is exercised against synthetic audio — Silero classifies
random noise inconsistently, so only structural properties (channel count,
sample rate, result shape) are asserted.  Acceptance testing against real
recordings is manual (see the PR description).
"""

import numpy as np
import pytest
from pydub import AudioSegment

from services.transcription.dsp.silence import _find_mask_runs
from services.transcription.dsp.audio_utils import (
    get_audio_mime_type,
    estimate_encoded_size_mb,
    is_single_shot_safe,
)
from services.transcription.dsp.debug import DEBUG_DSP


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

    def test_all_true(self):
        assert _find_mask_runs(np.ones(5, dtype=bool)) == [(0, 5)]

    def test_all_false(self):
        assert _find_mask_runs(np.zeros(5, dtype=bool)) == []


# ---------------------------------------------------------------------------
# hysteresis_speech_regions (no torch required — pure numpy)
# ---------------------------------------------------------------------------

class TestHysteresisSpeechRegions:
    def test_empty_probs(self):
        from services.transcription.dsp.vad import hysteresis_speech_regions
        assert hysteresis_speech_regions(np.zeros(0, dtype=np.float32)) == []

    def test_single_region(self):
        from services.transcription.dsp.vad import (
            hysteresis_speech_regions, FRAME_MS,
        )
        # 30 silent frames, 30 speech frames, 30 silent frames.
        probs = np.concatenate([
            np.zeros(30, dtype=np.float32),
            np.full(30, 0.9, dtype=np.float32),
            np.zeros(30, dtype=np.float32),
        ])
        regions = hysteresis_speech_regions(
            probs, p_hi=0.5, p_lo=0.35,
            min_speech_ms=FRAME_MS * 4,
            min_silence_ms=FRAME_MS * 4,
        )
        assert len(regions) == 1
        start, end = regions[0]
        assert start == pytest.approx(30 * FRAME_MS, abs=FRAME_MS)
        assert end == pytest.approx(60 * FRAME_MS, abs=FRAME_MS)


# ---------------------------------------------------------------------------
# _budget_keep_regions (no torch required — pure Python)
# ---------------------------------------------------------------------------

class TestBudgetKeepRegions:
    def test_no_speech_caps_whole_file(self):
        from services.transcription.dsp.pipeline import _budget_keep_regions
        keep, ann = _budget_keep_regions([], total_ms=5_000, max_silence_ms=800)
        assert ann == [(0.0, 5_000.0, 800.0)]
        assert keep == [(0.0, 400.0), (4_600.0, 5_000.0)]

    def test_short_gap_preserved(self):
        from services.transcription.dsp.pipeline import _budget_keep_regions
        keep, ann = _budget_keep_regions(
            [(200.0, 400.0)], total_ms=600.0, max_silence_ms=800,
        )
        assert ann == []
        assert keep == [(0.0, 600.0)]

    def test_long_gap_between_regions(self):
        from services.transcription.dsp.pipeline import _budget_keep_regions
        keep, ann = _budget_keep_regions(
            [(0.0, 1_000.0), (4_000.0, 5_000.0)],
            total_ms=5_000.0, max_silence_ms=800,
        )
        assert ann == [(1_000.0, 4_000.0, 800.0)]
        assert keep == [(0.0, 1_400.0), (3_600.0, 5_000.0)]


# ---------------------------------------------------------------------------
# Audio utilities
# ---------------------------------------------------------------------------

class TestGetAudioMimeType:
    def test_known_formats(self):
        assert get_audio_mime_type("test.mp3") == "audio/mpeg"
        assert get_audio_mime_type("test.wav") == "audio/wav"
        assert get_audio_mime_type("test.flac") == "audio/flac"
        assert get_audio_mime_type("test.webm") == "audio/webm"
        assert get_audio_mime_type("test.m4a") == "audio/mp4"

    def test_unknown_format(self):
        assert get_audio_mime_type("test.xyz") == "audio/mpeg"

    def test_no_extension(self):
        assert get_audio_mime_type("noextension") == "audio/mpeg"


class TestEstimateEncodedSizeMb:
    def test_wav_uncompressed(self):
        audio = _make_silent_audio(duration_ms=1000, sample_rate=16_000, channels=1)
        size = estimate_encoded_size_mb(audio, 'wav')
        assert 0.02 < size < 0.05

    def test_flac_smaller_than_wav(self):
        audio = _make_silent_audio(duration_ms=1000, sample_rate=16_000)
        assert (
            estimate_encoded_size_mb(audio, 'flac')
            < estimate_encoded_size_mb(audio, 'wav')
        )


class TestIsSingleShotSafe:
    def test_short_audio_is_safe(self):
        audio = _make_silent_audio(duration_ms=5_000, sample_rate=16_000)
        is_safe, _ = is_single_shot_safe(audio)
        assert is_safe is True

    def test_webm_uses_wav_format(self):
        audio = _make_silent_audio(duration_ms=1000, sample_rate=16_000)
        _, fmt = is_single_shot_safe(audio, source_format='webm')
        assert fmt == 'wav'

    def test_non_webm_uses_flac_format(self):
        audio = _make_silent_audio(duration_ms=1000, sample_rate=16_000)
        _, fmt = is_single_shot_safe(audio, source_format='mp3')
        assert fmt == 'flac'


# ---------------------------------------------------------------------------
# DEBUG_DSP
# ---------------------------------------------------------------------------

class TestDebugDsp:
    def test_debug_defaults_false(self):
        import os
        if os.environ.get("DSP_DEBUG", "").lower() not in ("1", "true", "yes"):
            assert DEBUG_DSP is False


# ---------------------------------------------------------------------------
# Integration smoke test (requires silero-vad + torch installed)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _pipeline():
    try:
        from services.transcription.dsp.pipeline import preprocess_for_transcription
    except ImportError as exc:
        pytest.skip(f"silero-vad / torch unavailable: {exc}")
    return preprocess_for_transcription


class TestPreprocessForTranscription:
    def test_preserves_channel_count(self, _pipeline):
        audio = _make_silent_audio(duration_ms=2_000, channels=1)
        result = _pipeline(audio)
        assert result.audio.channels == audio.channels

    def test_preserves_sample_rate(self, _pipeline):
        audio = _make_silent_audio(duration_ms=2_000, sample_rate=16_000)
        result = _pipeline(audio)
        assert result.audio.frame_rate == audio.frame_rate

    def test_returns_preprocess_result(self, _pipeline):
        audio = _make_silent_audio(duration_ms=2_000)
        result = _pipeline(audio)
        assert hasattr(result, 'audio')
        assert hasattr(result, 'excision_map')
        assert hasattr(result, 'waveform_overlay')

    @pytest.mark.parametrize("channels", [1, 2])
    def test_stereo_and_mono(self, _pipeline, channels):
        audio = _make_silent_audio(duration_ms=2_000, channels=channels)
        result = _pipeline(audio)
        assert result.audio.channels == channels
        assert result.audio.frame_rate == audio.frame_rate
