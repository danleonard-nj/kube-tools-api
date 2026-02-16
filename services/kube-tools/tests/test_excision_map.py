"""Tests for ExcisionMap timestamp remapping."""

import pytest

from services.transcription.models import ExcisionMap, WordToken


# ---------------------------------------------------------------------------
# Identity map
# ---------------------------------------------------------------------------

class TestIdentityMap:
    """When no excision occurs the map is 1:1."""

    def test_identity_returns_same_time(self):
        m = ExcisionMap.identity(10_000.0)
        assert m.to_original_time_ms(0.0) == pytest.approx(0.0)
        assert m.to_original_time_ms(5000.0) == pytest.approx(5000.0)
        assert m.to_original_time_ms(10_000.0) == pytest.approx(10_000.0)

    def test_identity_flag(self):
        m = ExcisionMap.identity(10_000.0)
        assert m.is_identity is True

    def test_non_identity_flag(self):
        m = ExcisionMap(
            keep_regions_ms=[(0.0, 2000.0), (3000.0, 5000.0)],
            original_duration_ms=5000.0,
            excised_duration_ms=4000.0,
        )
        assert m.is_identity is False


# ---------------------------------------------------------------------------
# Single excised region in the middle
# ---------------------------------------------------------------------------

class TestSingleExcision:
    """Original 10 s, silence excised at [3 s, 5 s)."""

    @pytest.fixture()
    def emap(self):
        # Keep [0,3000) and [5000,10000)
        return ExcisionMap(
            keep_regions_ms=[(0.0, 3000.0), (5000.0, 10_000.0)],
            original_duration_ms=10_000.0,
            excised_duration_ms=8000.0,  # 3000 + 5000
        )

    def test_before_excision(self, emap):
        """Timestamps before the gap are unchanged."""
        assert emap.to_original_time_ms(0.0) == pytest.approx(0.0)
        assert emap.to_original_time_ms(1500.0) == pytest.approx(1500.0)
        assert emap.to_original_time_ms(3000.0) == pytest.approx(3000.0)

    def test_after_excision(self, emap):
        """Timestamps after the gap are shifted by the excised duration."""
        # excised time 3000 → right at boundary, maps to 5000 (start of 2nd keep)
        # excised time 3001 → 5001
        assert emap.to_original_time_ms(3001.0) == pytest.approx(5001.0)
        assert emap.to_original_time_ms(5000.0) == pytest.approx(7000.0)
        # Last valid excised time = 8000 → original 10000
        assert emap.to_original_time_ms(8000.0) == pytest.approx(10_000.0)

    def test_at_boundary(self, emap):
        """At the excision boundary (excised 3000) we land at original 3000
        (end of first keep region) — the boundary is inclusive on the left
        of the next keep region, i.e. 5000."""
        # excised 3000 = exactly at the boundary between keep regions
        # Walk: region 0 is [0,3000), length 3000. 3000 <= 0+3000 → True
        # So result = 0 + (3000 - 0) = 3000  (end of first keep region)
        assert emap.to_original_time_ms(3000.0) == pytest.approx(3000.0)
        # excised 3000.01 falls into the second keep region
        assert emap.to_original_time_ms(3000.01) == pytest.approx(5000.01)


# ---------------------------------------------------------------------------
# Multiple excised regions
# ---------------------------------------------------------------------------

class TestMultipleExcisions:
    """Original 20 s, two excised regions: [4 s, 6 s) and [12 s, 15 s)."""

    @pytest.fixture()
    def emap(self):
        # Keep: [0, 4000), [6000, 12000), [15000, 20000)
        # Kept durations: 4000 + 6000 + 5000 = 15000
        return ExcisionMap(
            keep_regions_ms=[
                (0.0, 4000.0),
                (6000.0, 12_000.0),
                (15_000.0, 20_000.0),
            ],
            original_duration_ms=20_000.0,
            excised_duration_ms=15_000.0,
        )

    def test_first_region(self, emap):
        assert emap.to_original_time_ms(0.0) == pytest.approx(0.0)
        assert emap.to_original_time_ms(2000.0) == pytest.approx(2000.0)
        assert emap.to_original_time_ms(4000.0) == pytest.approx(4000.0)

    def test_second_region(self, emap):
        # excised 4000.5 → into second keep [6000,12000)
        # offset in second region = 4000.5 - 4000 = 0.5
        assert emap.to_original_time_ms(4000.5) == pytest.approx(6000.5)
        # excised 10000 → second keep, offset = 10000 - 4000 = 6000 → 6000+6000=12000
        assert emap.to_original_time_ms(10_000.0) == pytest.approx(12_000.0)

    def test_third_region(self, emap):
        # excised 10001 → into third keep [15000,20000)
        # offset in third region = 10001 - 10000 = 1
        assert emap.to_original_time_ms(10_001.0) == pytest.approx(15_001.0)
        # excised 15000 → 15000 + (15000 - 10000) = 20000
        assert emap.to_original_time_ms(15_000.0) == pytest.approx(20_000.0)

    def test_past_end_clamps(self, emap):
        """Timestamps beyond excised duration clamp to original end."""
        assert emap.to_original_time_ms(16_000.0) == pytest.approx(20_000.0)


# ---------------------------------------------------------------------------
# from_keep_runs factory
# ---------------------------------------------------------------------------

class TestFromKeepRuns:
    """Build an ExcisionMap from sample-index keep-runs."""

    def test_basic(self):
        # sr=1000 → 1 sample = 1 ms (easy arithmetic)
        m = ExcisionMap.from_keep_runs(
            keep_runs=[(0, 3000), (5000, 10_000)],
            sample_rate=1000,
            original_num_frames=10_000,
        )
        assert m.original_duration_ms == pytest.approx(10_000.0)
        assert m.excised_duration_ms == pytest.approx(8000.0)
        assert m.to_original_time_ms(4000.0) == pytest.approx(6000.0)

    def test_no_excision(self):
        m = ExcisionMap.from_keep_runs(
            keep_runs=[(0, 8000)],
            sample_rate=16000,
            original_num_frames=8000,
        )
        assert m.is_identity is True
        # 8000 frames at 16 kHz = 500 ms
        assert m.original_duration_ms == pytest.approx(500.0)

    def test_high_sample_rate(self):
        # sr=48000, 10 s audio = 480,000 frames
        # excise [96000, 192000) → [2 s, 4 s)
        m = ExcisionMap.from_keep_runs(
            keep_runs=[(0, 96_000), (192_000, 480_000)],
            sample_rate=48_000,
            original_num_frames=480_000,
        )
        assert m.original_duration_ms == pytest.approx(10_000.0)
        assert m.excised_duration_ms == pytest.approx(8000.0)
        # excised 3000 → original 5000
        assert m.to_original_time_ms(3000.0) == pytest.approx(5000.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_keep_regions(self):
        m = ExcisionMap(keep_regions_ms=[], original_duration_ms=5000.0, excised_duration_ms=0.0)
        # Should return input unchanged when no regions
        assert m.to_original_time_ms(100.0) == pytest.approx(100.0)

    def test_excision_at_start(self):
        """Silence at the very start of the audio."""
        m = ExcisionMap(
            keep_regions_ms=[(2000.0, 10_000.0)],
            original_duration_ms=10_000.0,
            excised_duration_ms=8000.0,
        )
        # excised time 0 → original 2000
        assert m.to_original_time_ms(0.0) == pytest.approx(2000.0)
        assert m.to_original_time_ms(4000.0) == pytest.approx(6000.0)

    def test_excision_at_end(self):
        """Silence at the very end of the audio."""
        m = ExcisionMap(
            keep_regions_ms=[(0.0, 7000.0)],
            original_duration_ms=10_000.0,
            excised_duration_ms=7000.0,
        )
        assert m.to_original_time_ms(0.0) == pytest.approx(0.0)
        assert m.to_original_time_ms(7000.0) == pytest.approx(7000.0)
        # Past end clamps
        assert m.to_original_time_ms(9000.0) == pytest.approx(7000.0)

    def test_fractional_timestamps(self):
        m = ExcisionMap(
            keep_regions_ms=[(0.0, 1500.5), (3000.0, 5000.0)],
            original_duration_ms=5000.0,
            excised_duration_ms=3500.5,
        )
        assert m.to_original_time_ms(750.25) == pytest.approx(750.25)
        # Into second region: offset = 1500.5
        assert m.to_original_time_ms(1501.0) == pytest.approx(3000.5)


# ---------------------------------------------------------------------------
# Integration: remap a list of WordTokens (mirrors transcription_service flow)
# ---------------------------------------------------------------------------

class TestWordTokenRemapping:
    """Simulate the timestamp remapping that transcription_service performs."""

    def test_remap_words(self):
        emap = ExcisionMap(
            keep_regions_ms=[(0.0, 2000.0), (4000.0, 8000.0)],
            original_duration_ms=8000.0,
            excised_duration_ms=6000.0,
        )

        # Simulated words in excised-audio seconds
        words = [
            WordToken(text="Hello", start=0.5, end=1.0, speaker="A"),
            WordToken(text="world", start=1.5, end=1.9, speaker="A"),
            # After the gap (excised 2000–4000):
            WordToken(text="how", start=2.1, end=2.5, speaker="B"),
            WordToken(text="are", start=2.6, end=3.0, speaker="B"),
            WordToken(text="you", start=3.1, end=3.5, speaker="B"),
        ]

        # Remap (same logic as transcription_service.py)
        for w in words:
            w.start = emap.to_original_time_ms(w.start * 1000.0) / 1000.0
            w.end = emap.to_original_time_ms(w.end * 1000.0) / 1000.0

        # Words before gap unchanged
        assert words[0].start == pytest.approx(0.5)
        assert words[0].end == pytest.approx(1.0)
        assert words[1].start == pytest.approx(1.5)
        assert words[1].end == pytest.approx(1.9)

        # Words after gap shifted by 2 s (the excised region)
        assert words[2].start == pytest.approx(4.1)
        assert words[2].end == pytest.approx(4.5)
        assert words[3].start == pytest.approx(4.6)
        assert words[3].end == pytest.approx(5.0)
        assert words[4].start == pytest.approx(5.1)
        assert words[4].end == pytest.approx(5.5)

        # Speaker labels preserved
        assert words[0].speaker == "A"
        assert words[2].speaker == "B"

    def test_remap_segments(self):
        emap = ExcisionMap(
            keep_regions_ms=[(0.0, 3000.0), (5000.0, 10_000.0)],
            original_duration_ms=10_000.0,
            excised_duration_ms=8000.0,
        )

        segments = [
            {"start": 1.0, "end": 2.5, "text": "first part", "speaker": "A"},
            {"start": 3.5, "end": 6.0, "text": "second part", "speaker": "B"},
        ]

        for seg in segments:
            seg["start"] = emap.to_original_time_ms(seg["start"] * 1000.0) / 1000.0
            seg["end"] = emap.to_original_time_ms(seg["end"] * 1000.0) / 1000.0

        # First segment: in first keep region, unchanged
        assert segments[0]["start"] == pytest.approx(1.0)
        assert segments[0]["end"] == pytest.approx(2.5)

        # Second segment: in second keep region, shifted by 2 s
        assert segments[1]["start"] == pytest.approx(5.5)
        assert segments[1]["end"] == pytest.approx(8.0)
