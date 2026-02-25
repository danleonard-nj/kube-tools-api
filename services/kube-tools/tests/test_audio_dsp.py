"""Unit tests for the DSP preprocessing pipeline.

Tests validate:
- _find_mask_runs: contiguous True-run finder
- limit_transients: brick-wall ceiling respected, lookahead applied
- compress_dynamic_range: gain reduction above threshold, speech-aware makeup
- _detect_silence_vad: silence regions detected, gap merging works
- preprocess_for_transcription: integration test with speech + silence
- get_audio_mime_type: MIME type lookups
- estimate_encoded_size_mb: size estimation sanity
- is_single_shot_safe: size gate with estimate-only approach
"""

import numpy as np
import pytest
from pydub import AudioSegment

from services.transcription.dsp.silence import (
    _find_mask_runs,
    _detect_silence_vad,
    _shape_injection_mask,
)
from services.transcription.dsp.compressor import (
    limit_transients,
    compress_dynamic_range,
)
from services.transcription.dsp.audio_utils import (
    get_audio_mime_type,
    estimate_encoded_size_mb,
    is_single_shot_safe,
)
from services.transcription.dsp.pipeline import preprocess_for_transcription
from services.transcription.dsp.debug import DEBUG_DSP


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silent_audio(
    duration_ms: int = 30_000,
    sample_rate: int = 48_000,
    channels: int = 1,
) -> AudioSegment:
    """Create a silent AudioSegment (all zeros)."""
    num_samples = int(duration_ms * sample_rate / 1000) * channels
    raw = np.zeros(num_samples, dtype=np.int16)
    return AudioSegment(
        raw.tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=channels,
    )


def _make_speech_with_silence(
    duration_ms: int = 10_000,
    silence_start_ms: int = 3_000,
    silence_end_ms: int = 7_000,
    sample_rate: int = 16_000,
    channels: int = 1,
    seed: int = 42,
) -> AudioSegment:
    """Create audio with speech-like noise bookending a long silence gap.

    [0 .. silence_start_ms)  → random noise at -20 dBFS (speech-like)
    [silence_start_ms .. silence_end_ms) → near-zero samples (silence)
    [silence_end_ms .. duration_ms)     → random noise (speech-like)
    """
    rng = np.random.RandomState(seed)
    num_frames = int(duration_ms * sample_rate / 1000)
    samples = np.zeros((num_frames, channels), dtype=np.int16)

    speech_amplitude = int(32768 * 10 ** (-20 / 20))  # ~-20 dBFS
    silence_start_sample = int(silence_start_ms * sample_rate / 1000)
    silence_end_sample = int(silence_end_ms * sample_rate / 1000)

    for ch in range(channels):
        speech_before = rng.randint(
            -speech_amplitude, speech_amplitude,
            size=silence_start_sample, dtype=np.int16,
        )
        speech_after = rng.randint(
            -speech_amplitude, speech_amplitude,
            size=num_frames - silence_end_sample, dtype=np.int16,
        )
        samples[:silence_start_sample, ch] = speech_before
        samples[silence_end_sample:, ch] = speech_after

    return AudioSegment(
        samples.flatten().tobytes(),
        frame_rate=sample_rate,
        sample_width=2,
        channels=channels,
    )


def _make_mono_float32(
    duration_ms: int = 500,
    sample_rate: int = 16_000,
    amplitude: float = 0.5,
    seed: int = 42,
) -> np.ndarray:
    """Create random float32 mono samples in [-amplitude, amplitude]."""
    rng = np.random.RandomState(seed)
    n = int(duration_ms * sample_rate / 1000)
    return (rng.randn(n) * amplitude).astype(np.float32)


# ---------------------------------------------------------------------------
# _find_mask_runs
# ---------------------------------------------------------------------------

class TestFindMaskRuns:
    """Validate the run-finding helper."""

    def test_empty(self):
        assert _find_mask_runs(np.array([], dtype=bool)) == []

    def test_single_run(self):
        mask = np.array([False, True, True, True, False], dtype=bool)
        runs = _find_mask_runs(mask)
        assert runs == [(1, 4)]

    def test_multiple_runs(self):
        mask = np.array([True, True, False, True, False, True, True], dtype=bool)
        runs = _find_mask_runs(mask)
        assert runs == [(0, 2), (3, 4), (5, 7)]

    def test_all_true(self):
        mask = np.ones(5, dtype=bool)
        runs = _find_mask_runs(mask)
        assert runs == [(0, 5)]

    def test_all_false(self):
        mask = np.zeros(5, dtype=bool)
        runs = _find_mask_runs(mask)
        assert runs == []


# ---------------------------------------------------------------------------
# limit_transients
# ---------------------------------------------------------------------------

class TestLimitTransients:
    """Validate the brick-wall limiter."""

    def test_ceiling_respected(self):
        """Output should not exceed the ceiling."""
        samples = _make_mono_float32(amplitude=0.9)
        ceiling_db = -6.0  # ~0.501
        limited, gain = limit_transients(samples, 16_000, ceiling_db=ceiling_db)

        ceiling_lin = 10.0 ** (ceiling_db / 20.0)
        assert np.max(np.abs(limited)) <= ceiling_lin + 1e-5

    def test_gain_envelope_shape(self):
        """Gain envelope should be same length as input and ≤ 1.0."""
        samples = _make_mono_float32(duration_ms=100)
        limited, gain = limit_transients(samples, 16_000, ceiling_db=-10.0)

        assert gain.shape == samples.shape
        assert np.all(gain <= 1.0 + 1e-6)
        assert np.all(gain > 0.0)

    def test_quiet_signal_unchanged(self):
        """A quiet signal below ceiling should pass through unchanged."""
        samples = _make_mono_float32(amplitude=0.01)
        limited, gain = limit_transients(samples, 16_000, ceiling_db=-6.0)

        # All gains should be 1.0 (no reduction needed)
        np.testing.assert_allclose(gain, 1.0, atol=1e-5)

    def test_returns_tuple(self):
        """Function returns (limited_mono, gain_envelope)."""
        samples = _make_mono_float32(duration_ms=50)
        result = limit_transients(samples, 16_000)
        assert isinstance(result, tuple)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# compress_dynamic_range
# ---------------------------------------------------------------------------

class TestCompressDynamicRange:
    """Validate the RMS compressor."""

    def test_gain_reduction_above_threshold(self):
        """Loud signal should have gain < 1.0."""
        samples = _make_mono_float32(amplitude=0.5)
        compressed, gain = compress_dynamic_range(
            samples, 16_000, threshold_db=-30.0,
        )

        # Some samples should have gain reduction
        assert np.any(gain < 1.0)

    def test_output_range(self):
        """Compressed mono should be clipped to [-1, 1]."""
        samples = _make_mono_float32(amplitude=0.8)
        compressed, gain = compress_dynamic_range(samples, 16_000)

        assert np.max(np.abs(compressed)) <= 1.0

    def test_returns_tuple(self):
        """Function returns (compressed_mono, gain_envelope)."""
        samples = _make_mono_float32(duration_ms=50)
        result = compress_dynamic_range(samples, 16_000)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0].shape == samples.shape
        assert result[1].shape == samples.shape

    def test_gain_includes_makeup(self):
        """Gain envelope should include makeup — may exceed 1.0 for quiet passages."""
        samples = _make_mono_float32(amplitude=0.01)
        compressed, gain = compress_dynamic_range(
            samples, 16_000, makeup_target_db=-16.0,
        )

        # Makeup gain should push some gain values above 1.0
        assert np.any(gain > 1.0)


# ---------------------------------------------------------------------------
# _detect_silence_vad
# ---------------------------------------------------------------------------

class TestDetectSilenceVad:
    """Validate VAD-based silence detection."""

    def test_detects_silence_in_mixed_audio(self):
        """Should detect the silence gap in a speech-silence-speech signal."""
        audio = _make_speech_with_silence(
            duration_ms=10_000,
            silence_start_ms=3_000,
            silence_end_ms=7_000,
            sample_rate=16_000,
        )
        raw = np.array(audio.get_array_of_samples(), dtype=np.int16)
        mono = raw.astype(np.float32) / 32768.0

        mask = _detect_silence_vad(
            mono, 16_000,
            aggressiveness=2,
            min_silence_ms=1000,
            min_gap_ms=400,
        )

        assert mask.shape == mono.shape
        assert mask.dtype == bool

        # The middle section should be mostly silence
        mid_start = int(3.5 * 16_000)
        mid_end = int(6.5 * 16_000)
        silence_fraction = np.mean(mask[mid_start:mid_end])
        assert silence_fraction > 0.5, (
            f"Expected middle section to be mostly silence, got {silence_fraction:.2%}"
        )

    def test_no_silence_in_continuous_speech(self):
        """Continuous noise should produce no silence detections."""
        rng = np.random.RandomState(99)
        sr = 16_000
        n = int(5.0 * sr)
        samples = (rng.randn(n) * 0.3).astype(np.float32)

        mask = _detect_silence_vad(
            samples, sr,
            aggressiveness=2,
            min_silence_ms=1000,
        )

        silence_fraction = np.mean(mask)
        assert silence_fraction < 0.3

    def test_energy_gate_catches_quiet_region(self):
        """Energy gate should detect near-silent regions that VAD misses
        when running on a compressed signal.

        Simulates the scenario where compression lifts a near-silent region
        (with a small non-speech sound) above the VAD's speech threshold.
        The energy gate uses the pre-compression signal to force those
        frames to silence.
        """
        sr = 16_000
        rng = np.random.RandomState(77)

        # Build: 2s speech | 3s near-silence (with a tiny bump) | 2s speech
        speech_amp = 0.3
        n_speech = int(2.0 * sr)
        n_quiet = int(3.0 * sr)
        total = 2 * n_speech + n_quiet

        # Pre-compression signal: quiet region at ~-55 dBFS with a small bump
        pre_comp = np.zeros(total, dtype=np.float32)
        pre_comp[:n_speech] = (rng.randn(n_speech) * speech_amp).astype(np.float32)
        pre_comp[n_speech + n_quiet:] = (rng.randn(n_speech) * speech_amp).astype(np.float32)
        # Tiny non-speech sound in the middle of the quiet region
        bump_start = n_speech + int(1.2 * sr)
        bump_len = int(0.3 * sr)
        pre_comp[bump_start:bump_start + bump_len] = (
            rng.randn(bump_len) * 0.005
        ).astype(np.float32)

        # Simulated post-compression signal: quiet region is amplified
        post_comp = pre_comp.copy()
        post_comp[n_speech:n_speech + n_quiet] *= 30.0  # simulate makeup gain

        # Without energy gate: VAD on compressed signal may miss the silence
        mask_no_gate = _detect_silence_vad(
            post_comp, sr,
            aggressiveness=2,
            min_silence_ms=1000,
            min_gap_ms=400,
        )

        # With energy gate: pre-compression reference catches it
        mask_with_gate = _detect_silence_vad(
            post_comp, sr,
            aggressiveness=2,
            min_silence_ms=1000,
            min_gap_ms=400,
            energy_ref=pre_comp,
            energy_gate_db=-40.0,
        )

        # The quiet region should be detected as silence with the energy gate
        quiet_start = n_speech + int(0.5 * sr)  # skip edges
        quiet_end = n_speech + n_quiet - int(0.5 * sr)
        gate_fraction = np.mean(mask_with_gate[quiet_start:quiet_end])
        assert gate_fraction > 0.5, (
            f"Energy gate should detect the quiet region as silence, "
            f"got {gate_fraction:.2%}"
        )

    def test_adaptive_gate_preserves_quiet_speech(self):
        """Adaptive gate should not excise quiet speech.

        When the speaker is quiet, the pre-compression speech level may
        hover near the fixed -40 dBFS gate threshold, causing portions of
        speech to be incorrectly gated.  The adaptive gate should lower
        the threshold based on the actual speech level so that quiet
        speech is preserved while true silence is still gated.
        """
        sr = 16_000
        rng = np.random.RandomState(88)

        # Build: 2s quiet speech | 3s true silence | 2s quiet speech
        speech_amp = 0.02  # ~-34 dBFS RMS — near the old fixed gate
        n_speech = int(2.0 * sr)
        n_quiet = int(3.0 * sr)
        total = 2 * n_speech + n_quiet

        pre_comp = np.zeros(total, dtype=np.float32)
        pre_comp[:n_speech] = (rng.randn(n_speech) * speech_amp).astype(np.float32)
        pre_comp[n_speech + n_quiet:] = (rng.randn(n_speech) * speech_amp).astype(np.float32)
        # Add ambient noise floor in the silence region
        pre_comp[n_speech:n_speech + n_quiet] = (
            rng.randn(n_quiet) * 0.0005
        ).astype(np.float32)

        # Simulated post-compression: quiet speech lifted to normal levels
        post_comp = pre_comp.copy()
        post_comp *= 15.0  # simulate makeup gain

        # With fixed gate at -40: quiet speech near -34 dBFS has samples
        # that dip below -40, incorrectly gating speech
        mask_fixed = _detect_silence_vad(
            post_comp, sr,
            aggressiveness=2,
            min_silence_ms=1000,
            min_gap_ms=400,
            energy_ref=pre_comp,
            energy_gate_db=-40.0,
            energy_gate_headroom_db=0.0,  # disable adaptive → fixed gate
        )

        # With adaptive gate: threshold drops below quiet speech
        mask_adaptive = _detect_silence_vad(
            post_comp, sr,
            aggressiveness=2,
            min_silence_ms=1000,
            min_gap_ms=400,
            energy_ref=pre_comp,
            energy_gate_db=-40.0,
            energy_gate_headroom_db=20.0,
        )

        # Check speech regions are preserved with adaptive gate
        speech_region = np.concatenate([
            mask_adaptive[:n_speech],
            mask_adaptive[n_speech + n_quiet:],
        ])
        speech_silence_frac = np.mean(speech_region)
        assert speech_silence_frac < 0.3, (
            f"Adaptive gate should preserve quiet speech, "
            f"but {speech_silence_frac:.0%} of speech was marked as silence"
        )

        # Check silence region is still detected
        quiet_start = n_speech + int(0.5 * sr)
        quiet_end = n_speech + n_quiet - int(0.5 * sr)
        silence_frac = np.mean(mask_adaptive[quiet_start:quiet_end])
        assert silence_frac > 0.5, (
            f"Adaptive gate should still detect true silence, "
            f"got {silence_frac:.2%}"
        )


# ---------------------------------------------------------------------------
# _shape_injection_mask
# ---------------------------------------------------------------------------

class TestShapeInjectionMask:
    """Validate grace/tail mask shaping."""

    def test_grace_tail_carving(self):
        """Mask should preserve grace period at start and tail at end."""
        sr = 16_000
        n = int(5.0 * sr)
        # Create a silence region from 1s to 4s
        coarse = np.zeros(n, dtype=bool)
        coarse[sr:4 * sr] = True  # 3 seconds of silence

        shaped = _shape_injection_mask(
            coarse, coarse, sr,
            grace_ms=200, tail_ms=200,
        )

        # Grace region (first 200ms of silence) should NOT be excised
        grace_end = sr + int(0.2 * sr)
        assert not np.any(shaped[:grace_end])

        # Tail region (last 200ms of silence) should NOT be excised
        tail_start = 4 * sr - int(0.2 * sr)
        assert not np.any(shaped[tail_start:4 * sr])

        # Interior should be excised
        interior_start = grace_end + 100
        interior_end = tail_start - 100
        assert np.any(shaped[interior_start:interior_end])

    def test_short_silence_skipped(self):
        """Silence shorter than grace+tail should not be excised."""
        sr = 16_000
        n = int(2.0 * sr)
        coarse = np.zeros(n, dtype=bool)
        # 200ms silence — shorter than grace(150)+tail(150)=300ms
        coarse[sr:sr + int(0.2 * sr)] = True

        shaped = _shape_injection_mask(
            coarse, coarse, sr,
            grace_ms=150, tail_ms=150,
        )

        assert not np.any(shaped)


# ---------------------------------------------------------------------------
# Audio utilities
# ---------------------------------------------------------------------------

class TestGetAudioMimeType:
    """Validate MIME type lookup."""

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
    """Validate size estimation."""

    def test_wav_uncompressed(self):
        audio = _make_silent_audio(duration_ms=1000, sample_rate=16_000, channels=1)
        size = estimate_encoded_size_mb(audio, 'wav')
        # 16000 * 1 * 2 bytes * 1 sec = 32000 bytes ≈ 0.031 MB
        assert 0.02 < size < 0.05

    def test_flac_smaller_than_wav(self):
        audio = _make_silent_audio(duration_ms=1000, sample_rate=16_000)
        wav_size = estimate_encoded_size_mb(audio, 'wav')
        flac_size = estimate_encoded_size_mb(audio, 'flac')
        assert flac_size < wav_size


class TestIsSingleShotSafe:
    """Validate the size-gate function (estimate-only approach)."""

    def test_short_audio_is_safe(self):
        audio = _make_silent_audio(duration_ms=5000, sample_rate=16_000)
        is_safe, fmt = is_single_shot_safe(audio)
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
    """Verify DEBUG_DSP defaults to False (env-driven)."""

    def test_debug_defaults_false(self):
        """DEBUG_DSP should be False unless DSP_DEBUG env var is set."""
        import os
        if os.environ.get("DSP_DEBUG", "").lower() not in ("1", "true", "yes"):
            assert DEBUG_DSP is False


# ---------------------------------------------------------------------------
# Integration: preprocess_for_transcription
# ---------------------------------------------------------------------------

class TestPreprocessForTranscription:
    """Integration test for the full pipeline."""

    def test_preserves_channel_count(self):
        """Output should have the same channel count as input."""
        audio = _make_speech_with_silence(channels=1)
        result = preprocess_for_transcription(audio)
        assert result.audio.channels == audio.channels

    def test_preserves_sample_rate(self):
        """Output should have the same sample rate as input."""
        audio = _make_speech_with_silence()
        result = preprocess_for_transcription(audio)
        assert result.audio.frame_rate == audio.frame_rate

    def test_returns_preprocess_result(self):
        """Should return a PreprocessResult with audio, excision_map, overlay."""
        audio = _make_speech_with_silence()
        result = preprocess_for_transcription(audio)
        assert hasattr(result, 'audio')
        assert hasattr(result, 'excision_map')
        assert hasattr(result, 'waveform_overlay')

    def test_excision_shortens_audio(self):
        """Audio with a long silence gap should be shorter after excision."""
        audio = _make_speech_with_silence(
            duration_ms=10_000,
            silence_start_ms=3_000,
            silence_end_ms=7_000,
        )
        result = preprocess_for_transcription(audio, min_silence_ms=1000)

        # Should be shorter — the 4s silence gap should be at least partially removed
        assert len(result.audio) < len(audio)

    def test_excision_map_not_identity_when_excised(self):
        """ExcisionMap should not be identity when silence was excised."""
        audio = _make_speech_with_silence(
            duration_ms=10_000,
            silence_start_ms=3_000,
            silence_end_ms=7_000,
        )
        result = preprocess_for_transcription(audio, min_silence_ms=1000)

        if len(result.audio) < len(audio):
            assert not result.excision_map.is_identity

    @pytest.mark.parametrize("channels", [1, 2])
    def test_stereo_and_mono(self, channels):
        """Pipeline should work for both mono and stereo input."""
        audio = _make_speech_with_silence(channels=channels)
        result = preprocess_for_transcription(audio)
        assert result.audio.channels == channels
        assert result.audio.frame_rate == audio.frame_rate
