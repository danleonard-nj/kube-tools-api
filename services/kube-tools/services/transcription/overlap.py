"""Overlap trimming and text seam deduplication for chunk boundaries."""

import re
from typing import List, Dict

from framework.logger import get_logger
from services.transcription.models import WordToken

logger = get_logger(__name__)


_WORD_RE = re.compile(r"\S+")
_NORM_STRIP = re.compile(r"[^\w']+", re.UNICODE)


def _normalize_token(tok: str) -> str:
    """Lowercase + strip leading/trailing non-word punctuation for comparison."""
    return _NORM_STRIP.sub("", tok).lower()


def trim_word_tokens_in_overlap_window(
    words: List[WordToken],
    overlap_end_sec: float,
    epsilon: float = 0.01
) -> List[WordToken]:
    """
    Deterministic overlap trimming for word tokens.

    The previous chunk *owns* the time interval up to ``overlap_end_sec``.
    Any new word whose ``start`` falls before that boundary (minus a small
    epsilon) is dropped.

    Args:
        words: New word tokens (already offset to global time)
        overlap_end_sec: The global-time boundary owned by the previous chunk
        epsilon: Small tolerance in seconds (default 10ms)

    Returns:
        Words that start at or after the boundary
    """
    boundary = overlap_end_sec - epsilon
    return [w for w in words if w.start >= boundary]


def trim_segments_in_overlap_window(
    segments: List[Dict],
    overlap_end_sec: float,
    epsilon: float = 0.01
) -> List[Dict]:
    """
    Deterministic overlap trimming for segments.

    Drops segments whose ``start`` time falls within the overlap window
    owned by the previous chunk.

    Args:
        segments: New segments (already offset to global time)
        overlap_end_sec: The global-time boundary owned by the previous chunk
        epsilon: Small tolerance in seconds (default 10ms)

    Returns:
        Segments that start at or after the boundary
    """
    boundary = overlap_end_sec - epsilon
    return [s for s in segments if s.get('start', 0) >= boundary]


def find_overlap_suffix_prefix(prev_text: str, new_text: str, max_overlap: int = 80) -> int:
    """
    Find the longest overlapping text between the suffix of prev_text and prefix of new_text.

    Used for de-duplication at chunk boundaries.  Matches at the **word**
    level after normalizing case and stripping non-word punctuation, so that
    re-transcribed overlap text like ``"...see how this"`` followed by
    ``"See how this interprets..."`` still matches.

    Args:
        prev_text: Previous chunk's text
        new_text: New chunk's text
        max_overlap: Maximum characters of *new_text* to ever consume

    Returns:
        Number of leading characters to trim from ``new_text`` (literal
        characters in the original string, including any whitespace before
        the first matched word).
    """
    if not prev_text or not new_text:
        return 0

    # Tokenize with span info so we can map back to character offsets.
    new_matches = list(_WORD_RE.finditer(new_text))
    prev_matches = list(_WORD_RE.finditer(prev_text))
    if not new_matches or not prev_matches:
        return 0

    new_norm = [_normalize_token(m.group(0)) for m in new_matches]
    prev_norm = [_normalize_token(m.group(0)) for m in prev_matches]

    # Cap how many tokens of new we'll consider (rough char budget).
    cap_tokens = len(new_matches)
    cum_chars = 0
    for i, m in enumerate(new_matches):
        cum_chars = m.end()
        if cum_chars > max_overlap:
            cap_tokens = i
            break
    if cap_tokens < 1:
        return 0

    max_k = min(cap_tokens, len(prev_norm))
    for k in range(max_k, 0, -1):
        prev_tail = prev_norm[-k:]
        new_head = new_norm[:k]
        if all(p and p == n for p, n in zip(prev_tail, new_head)):
            trim_chars = new_matches[k - 1].end()
            logger.debug(
                "Found %d-word seam overlap: '%s'", k, " ".join(new_head),
            )
            return trim_chars
    return 0


def deduplicate_seam(prev_text: str, new_text: str, max_overlap: int = 80) -> str:
    """
    Remove duplicate text from new_text that overlaps with the end of prev_text.

    Args:
        prev_text: Previous accumulated text
        new_text: New text to append
        max_overlap: Maximum characters to check for overlap

    Returns:
        Deduplicated new_text with overlap removed
    """
    trim_len = find_overlap_suffix_prefix(prev_text, new_text, max_overlap)
    if trim_len > 0:
        return new_text[trim_len:].lstrip()
    return new_text
