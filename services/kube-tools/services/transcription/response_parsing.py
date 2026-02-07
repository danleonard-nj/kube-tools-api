"""Pure-function extraction of OpenAI transcription API responses."""

import re
from typing import List, Dict, Tuple

from framework.logger import get_logger
from services.transcription.models import AudioChunk, WordToken
from services.transcription.segmentation import infer_word_tokens_from_segments

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
        logger.debug(f"Chunk {chunk.chunk_index}: Inferring word timing from {len(segments)} segments")
        words = infer_word_tokens_from_segments(segments)

    logger.info(f"Chunk {chunk.chunk_index} parsed: {len(chunk_text)} chars, "
                f"{len(segments)} segments, {len(words)} words")

    return chunk_text.strip(), segments, words


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
