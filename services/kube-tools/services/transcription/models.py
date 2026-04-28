"""Shared data classes for the transcription pipeline."""

from typing import List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from pydub import AudioSegment


@dataclass
class ExcisionMap:
    """Maps timestamps from excised (processed) audio back to original audio
    coordinates.

    After silence excision, the processed audio is shorter than the original.
    This map translates timestamps from the excised timeline back to their
    correct positions in the original timeline.

    Attributes:
        keep_regions_ms: Sorted list of ``(original_start_ms, original_end_ms)``
            for every kept (non-excised) region.  These regions appear
            contiguously in the excised audio.
        original_duration_ms: Duration of the original (pre-excision) audio.
        excised_duration_ms: Duration of the excised (post-processing) audio.
    """

    keep_regions_ms: List[Tuple[float, float]] = field(default_factory=list)
    original_duration_ms: float = 0.0
    excised_duration_ms: float = 0.0

    # ------------------------------------------------------------------
    # Factories
    # ------------------------------------------------------------------

    @staticmethod
    def identity(duration_ms: float) -> "ExcisionMap":
        """Create an identity map (no excision performed)."""
        return ExcisionMap(
            keep_regions_ms=[(0.0, duration_ms)],
            original_duration_ms=duration_ms,
            excised_duration_ms=duration_ms,
        )

    @staticmethod
    def from_keep_runs(
        keep_runs: List[Tuple[int, int]],
        sample_rate: int,
        original_num_frames: int,
    ) -> "ExcisionMap":
        """Build an ExcisionMap from sample-index keep-runs.

        Args:
            keep_runs: ``[(start_sample, end_sample), ...]`` of kept regions
                in original-audio sample indices (sorted by start).
            sample_rate: Audio sample rate in Hz.
            original_num_frames: Total number of samples in the original audio.
        """
        keep_regions_ms = [
            (s * 1000.0 / sample_rate, e * 1000.0 / sample_rate)
            for s, e in keep_runs
        ]
        excised_samples = sum(e - s for s, e in keep_runs)
        return ExcisionMap(
            keep_regions_ms=keep_regions_ms,
            original_duration_ms=original_num_frames * 1000.0 / sample_rate,
            excised_duration_ms=excised_samples * 1000.0 / sample_rate,
        )

    # ------------------------------------------------------------------
    # Mapping helpers
    # ------------------------------------------------------------------

    def to_original_time_ms(self, excised_time_ms: float) -> float:
        """Map a timestamp from excised-audio coordinates to original-audio
        coordinates.

        Walks through the keep regions, accumulating their lengths in
        excised-audio time, and returns the corresponding position in
        original-audio time.
        """
        if not self.keep_regions_ms:
            return excised_time_ms

        excised_offset = 0.0
        for orig_start, orig_end in self.keep_regions_ms:
            region_len = orig_end - orig_start
            if excised_time_ms <= excised_offset + region_len:
                return orig_start + (excised_time_ms - excised_offset)
            excised_offset += region_len

        # Past all regions — clamp to end of last region
        return self.keep_regions_ms[-1][1]

    @property
    def is_identity(self) -> bool:
        """True when no excision was performed (1:1 mapping)."""
        return (
            len(self.keep_regions_ms) == 1
            and abs(self.keep_regions_ms[0][0]) < 0.01
            and abs(self.keep_regions_ms[0][1] - self.original_duration_ms) < 0.01
        )


@dataclass
class PreprocessResult:
    """Packages the output of the DSP preprocessing pipeline.

    Attributes:
        audio: The (now unmodified) original ``AudioSegment``.
        excision_map: Identity map (kept for API compatibility).
        waveform_overlay: Optional base64-encoded PNG overlay.
        chunks: VAD-planned, overlap-padded ``AudioChunk`` list.
        chunk_plan: Per-chunk decision log (winners + losers).
        vad_probs: Per-frame Silero P(speech) trace (32 ms resolution).
    """

    audio: AudioSegment
    excision_map: "ExcisionMap"
    waveform_overlay: Optional[str] = None
    chunks: List["AudioChunk"] = field(default_factory=list)
    chunk_plan: List["ChunkPlanEntry"] = field(default_factory=list)
    vad_probs: Optional["object"] = None  # numpy.ndarray; avoids hard import here


@dataclass
class AudioChunk:
    """
    Represents a chunk of audio data with metadata.

    Attributes:
        audio_segment: The actual audio data for this chunk (post-excision
            if excision was applied)
        logical_start_ms: Start time of the content (without overlap)
        logical_end_ms: End time of the content (without overlap)
        actual_start_ms: Start time including overlap padding
        actual_end_ms: End time including overlap padding
        chunk_index: Index of this chunk in the sequence
        excision_map: Maps timestamps inside ``audio_segment`` (excised,
            chunk-local ms) back to chunk-local ms in the *original*
            (un-excised) chunk window.  ``None`` means no excision was
            applied (1:1 mapping).
    """
    audio_segment: Optional[AudioSegment]
    logical_start_ms: float
    logical_end_ms: float
    actual_start_ms: float
    actual_end_ms: float
    chunk_index: int
    excision_map: Optional["ExcisionMap"] = None


@dataclass
class WordToken:
    """
    Represents a single word token with timing and speaker information.

    This is the source of truth for word-level timing in the transcription.

    Attributes:
        text: The word text (including punctuation)
        start: Start time in seconds
        end: End time in seconds
        speaker: Optional speaker label (e.g., 'Speaker 1')
    """
    text: str
    start: float
    end: float
    speaker: Optional[str] = None


@dataclass
class BoundaryScore:
    """Confidence score for a candidate split point inside a silence gap.

    All feature values are in [0, 1].  ``confidence`` is the equally-weighted
    sum of the four features (also in [0, 1]).
    """
    gap_start_ms: float
    gap_end_ms: float
    midpoint_ms: float
    duration: float
    stability: float
    restart_strength: float
    depth: float
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChunkPlanEntry:
    """One entry in a chunk plan — winner and losers for a single chunk."""
    chunk_index: int
    start_ms: float
    end_ms: float
    boundary_type: str  # "natural" | "forced" | "end_of_audio"
    chosen_boundary: Optional[BoundaryScore] = None
    rejected_candidates: List[BoundaryScore] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "boundary_type": self.boundary_type,
            "chosen_boundary": self.chosen_boundary.to_dict() if self.chosen_boundary else None,
            "rejected_candidates": [c.to_dict() for c in self.rejected_candidates],
        }
