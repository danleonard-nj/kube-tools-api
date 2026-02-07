"""Overlap trimming and text seam deduplication for chunk boundaries."""

from typing import List, Dict

from framework.logger import get_logger
from services.transcription.models import WordToken

logger = get_logger(__name__)


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

    This is used to de-duplicate text at chunk boundaries caused by overlapping audio.

    Args:
        prev_text: Previous chunk's text
        new_text: New chunk's text
        max_overlap: Maximum characters to check for overlap

    Returns:
        Number of characters to trim from the start of new_text
    """
    if not prev_text or not new_text:
        return 0

    # Check progressively smaller overlaps
    check_len = min(max_overlap, len(prev_text), len(new_text))

    for overlap_len in range(check_len, 0, -1):
        prev_suffix = prev_text[-overlap_len:]
        new_prefix = new_text[:overlap_len]

        if prev_suffix == new_prefix:
            logger.debug(f"Found {overlap_len}-char overlap: '{prev_suffix}'")
            return overlap_len

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
