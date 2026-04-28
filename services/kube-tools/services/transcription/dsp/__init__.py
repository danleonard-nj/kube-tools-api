"""Public API for the DSP preprocessing pipeline.

Usage::

    from services.transcription.dsp import (
        preprocess_for_transcription,
        get_audio_mime_type,
        plan_chunks,
        score_boundary,
    )
"""

from .audio_utils import estimate_encoded_size_mb, get_audio_mime_type
from .overlay import render_chunk_plan_overlay, render_chunk_plan_table
from .pipeline import preprocess_for_transcription
from .planner import (
    CONFIDENCE_THRESHOLD, MAX_CHUNK_MS, MIN_BOUNDARY_SILENCE_MS, MIN_CHUNK_MS,
    OVERLAP_MS, materialize_chunks, plan_chunks,
)
from .scoring import score_boundary
from .vad import FRAME_MS, VAD_SR, compute_speech_probabilities, hysteresis_speech_regions

