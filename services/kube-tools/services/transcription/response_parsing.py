"""Pure-function extraction of OpenAI transcription API responses."""

import re
from typing import List, Dict, Tuple

from framework.logger import get_logger
from services.transcription.models import AudioChunk, WordToken
from services.transcription.segmentation import (
    infer_word_tokens_from_segments,
    tokenize_text,
)
from services.transcription.word_alignment import (
    WORD_ALIGNMENT_MODE,
    align_words_silence_aware,
)

logger = get_logger(__name__)

# Regex to detect 4+ repeated consonants (music/noise artifacts)
NON_LEXICAL_RE = re.compile(r'([bcdfghjklmnpqrstvwxyz])\1{3,}', re.I)


def is_non_lexical_noise(segment_text: str) -> bool:
    """
    Detect non-lexical artifacts from music encoding (e.g., "Brrrrrrrrrrr", "ssssssss").

    Rule (tight, safe):
    - Drop any segment that is:
      - >= 4 repeated consonants
      - AND contains no vowels
      - AND is at least 6 characters

    This will remove garbage like "Brrrrrrrrrr" without touching real words.

    Args:
        segment_text: Text from a transcription segment

    Returns:
        True if segment appears to be non-lexical noise, False otherwise
    """
    t = segment_text.strip().lower()
    if len(t) < 6:
        return False
    if any(v in t for v in "aeiou"):
        return False
    return bool(NON_LEXICAL_RE.search(t))


def parse_transcription_response(
    response,
    chunk: AudioChunk
) -> Tuple[str, List[Dict], List[WordToken]]:
    """
    Convert an OpenAI transcription response into normalised
    (text, segments, words).

    Handles string, dict, and Pydantic-model response shapes.
    Timestamps in returned segments are offset to global time using
    ``chunk.actual_start_ms``.

    Args:
        response: Raw response from ``client.audio.transcriptions.create``
        chunk: The AudioChunk that was sent (used for timestamp offset)

    Returns:
        Tuple of (chunk_text, segments, words)
    """
    chunk_text = ""
    segments: List[Dict] = []

    if isinstance(response, str):
        chunk_text = response
    elif hasattr(response, 'text'):
        chunk_text = response.text
        if hasattr(response, 'segments') and response.segments:
            offset_sec = chunk.actual_start_ms / 1000.0
            for seg in response.segments:
                seg_dict = _segment_to_dict(seg)
                seg_start = seg_dict.get('start', 0)
                seg_end = seg_dict.get('end', 0)
                seg_dict['start'] = offset_sec + seg_start
                seg_dict['end'] = offset_sec + seg_end
                if 'text' in seg_dict:
                    seg_dict['text'] = seg_dict['text'].strip()
                segments.append(seg_dict)
        else:
            if chunk_text.strip():
                segments.append({
                    'start': chunk.actual_start_ms / 1000.0,
                    'end': chunk.actual_end_ms / 1000.0,
                    'text': chunk_text.strip()
                })
    elif isinstance(response, dict):
        chunk_text = response.get('text', '')
        if 'segments' in response and response['segments']:
            offset_sec = chunk.actual_start_ms / 1000.0
            for seg in response['segments']:
                seg_dict = dict(seg)
                seg_dict['start'] = offset_sec + seg.get('start', 0)
                seg_dict['end'] = offset_sec + seg.get('end', 0)
                if 'text' in seg_dict:
                    seg_dict['text'] = seg_dict['text'].strip()
                segments.append(seg_dict)
    else:
        chunk_text = str(response)

    # Filter out non-lexical noise artifacts (music encoding, etc.)
    if segments:
        original_count = len(segments)
        segments = [
            s for s in segments
            if not is_non_lexical_noise(s.get('text', ''))
        ]
        filtered_count = original_count - len(segments)
        if filtered_count > 0:
            logger.info(f"Chunk {chunk.chunk_index}: Filtered {filtered_count} non-lexical noise segment(s)")

    # Infer word-level timing from segments
    words: List[WordToken] = []
    if segments:
        if WORD_ALIGNMENT_MODE == "silence_aware":
            words = _align_words_with_energy(
                segments, chunk, chunk.chunk_index
            )
        if not words:
            # Uniform fallback (mode == "uniform" or silence-aware produced nothing)
            logger.debug(f"Chunk {chunk.chunk_index}: Inferring word timing (uniform) from {len(segments)} segments")
            words = infer_word_tokens_from_segments(segments)

    logger.info(f"Chunk {chunk.chunk_index} parsed: {len(chunk_text)} chars, "
                f"{len(segments)} segments, {len(words)} words")

    return chunk_text.strip(), segments, words


def _align_words_with_energy(
    segments: List[Dict],
    chunk: AudioChunk,
    chunk_index: int,
) -> List[WordToken]:
    """
    Attempt silence-aware alignment for every segment in *segments*.

    Falls back to uniform distribution (returns ``[]``) on any exception
    so the caller can use the legacy path.
    """
    audio_seg = getattr(chunk, "audio_segment", None)
    if audio_seg is None:
        logger.debug(f"Chunk {chunk_index}: no audio_segment on chunk, skipping silence-aware alignment")
        return []

    all_words: List[WordToken] = []
    offset_sec = chunk.actual_start_ms / 1000.0

    for seg in segments:
        seg_text = seg.get("text", "").strip()
        if not seg_text:
            continue

        seg_start_sec = seg.get("start", 0.0)
        seg_end_sec = seg.get("end", 0.0)
        speaker = seg.get("speaker")
        tokens = tokenize_text(seg_text)
        if not tokens:
            continue

        # Segment times are already global (offset applied in parse step above).
        # Convert to ms relative to the *audio_segment* origin (actual_start_ms).
        local_start_ms = int((seg_start_sec - offset_sec) * 1000)
        local_end_ms = int((seg_end_sec - offset_sec) * 1000)

        # Clamp to audio bounds
        audio_len_ms = len(audio_seg)
        local_start_ms = max(0, min(local_start_ms, audio_len_ms))
        local_end_ms = max(local_start_ms, min(local_end_ms, audio_len_ms))

        if local_end_ms - local_start_ms <= 0:
            continue

        try:
            aligned = align_words_silence_aware(
                audio_seg,
                local_start_ms,
                local_end_ms,
                tokens,
                speaker=speaker,
            )
            for wd in aligned:
                # Convert local-ms back to global seconds
                w_start_sec = wd["start_ms"] / 1000.0 + offset_sec
                w_end_sec = wd["end_ms"] / 1000.0 + offset_sec
                all_words.append(WordToken(
                    text=wd["word"],
                    start=w_start_sec,
                    end=w_end_sec,
                    speaker=wd.get("speaker"),
                ))
        except Exception:
            logger.warning(
                f"Chunk {chunk_index}: silence-aware alignment failed for segment "
                f"{seg_start_sec:.2f}-{seg_end_sec:.2f}s, falling back to uniform",
                exc_info=True,
            )
            return []  # signal caller to use full uniform fallback

    return all_words


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _segment_to_dict(seg) -> Dict:
    """Convert a single segment (dict or Pydantic model) to a plain dict."""
    if isinstance(seg, dict):
        return dict(seg)

    # Pydantic v2
    if hasattr(seg, 'model_dump'):
        return seg.model_dump()
    # Pydantic v1
    if hasattr(seg, 'dict'):
        return seg.dict()

    # Last resort: manual extraction
    return {
        'id': getattr(seg, 'id', None),
        'start': getattr(seg, 'start', 0),
        'end': getattr(seg, 'end', 0),
        'text': getattr(seg, 'text', ''),
        'speaker': getattr(seg, 'speaker', None),
        'type': getattr(seg, 'type', None)
    }
