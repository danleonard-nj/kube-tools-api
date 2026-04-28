"""Pure-function extraction of OpenAI transcription API responses,
plus a provider-agnostic globaliser used by the transcription service.
"""

from typing import List, Dict, Tuple, Optional, Any

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


# ---------------------------------------------------------------------------
# OpenAI response → (text, local_segments)
# ---------------------------------------------------------------------------

def extract_openai_text_and_segments(response) -> Tuple[str, List[Dict[str, Any]]]:
    """Pull text + chunk-local segment dicts out of any OpenAI response shape.

    Used by :class:`OpenAIProvider`.  Timestamps in the returned segments
    are kept in the API's chunk-local seconds (the caller globalises
    them via the chunk's excision map).
    """
    text = ""
    local_segments: List[Dict[str, Any]] = []

    if isinstance(response, str):
        text = response
    elif hasattr(response, 'text'):
        text = response.text or ""
        if hasattr(response, 'segments') and response.segments:
            for seg in response.segments:
                seg_dict = _segment_to_dict(seg)
                if 'text' in seg_dict and isinstance(seg_dict['text'], str):
                    seg_dict['text'] = seg_dict['text'].strip()
                local_segments.append(seg_dict)
    elif isinstance(response, dict):
        text = response.get('text', '')
        if 'segments' in response and response['segments']:
            for seg in response['segments']:
                seg_dict = dict(seg)
                if 'text' in seg_dict and isinstance(seg_dict['text'], str):
                    seg_dict['text'] = seg_dict['text'].strip()
                local_segments.append(seg_dict)
    else:
        text = str(response)

    return text.strip(), local_segments


# ---------------------------------------------------------------------------
# Provider-agnostic local → global mapping
# ---------------------------------------------------------------------------

def globalize_chunk_result(
    text: str,
    local_segments: Optional[List[Dict[str, Any]]],
    chunk: AudioChunk,
) -> Tuple[str, List[Dict], List[WordToken]]:
    """Convert any provider's chunk-local result into globalised
    ``(text, segments, words)`` suitable for the merge step.

    If the provider supplied no segments, a synthetic one spanning the
    whole excised chunk is used so silence-aware word alignment can
    still produce timings.
    """
    excised_len_sec = float(len(chunk.audio_segment)) / 1000.0
    segs: List[Dict[str, Any]] = list(local_segments or [])
    if not segs and text.strip():
        segs.append({
            'start': 0.0,
            'end': excised_len_sec,
            'text': text.strip(),
        })

    local_words: List[WordToken] = []
    if segs:
        if WORD_ALIGNMENT_MODE == "silence_aware":
            local_words = _align_words_with_energy_local(
                segs, chunk, chunk.chunk_index,
            )
        if not local_words:
            logger.debug(
                f"Chunk {chunk.chunk_index}: Inferring word timing (uniform) "
                f"from {len(segs)} segments"
            )
            local_words = infer_word_tokens_from_segments(segs)

    segments_global = [_globalize_segment(s, chunk) for s in segs]
    words_global = [
        WordToken(
            text=w.text,
            start=_excised_local_to_global_sec(w.start, chunk),
            end=_excised_local_to_global_sec(w.end, chunk),
            speaker=w.speaker,
        )
        for w in local_words
    ]
    return text.strip(), segments_global, words_global


def _excised_local_to_global_sec(local_excised_sec: float, chunk: AudioChunk) -> float:
    """Map excised-local seconds → global seconds via the chunk's excision map.

    For chunks without excision (``excision_map is None`` or the identity
    map), this is just ``actual_start_ms/1000 + local_excised_sec``.
    Otherwise we walk through the kept regions to recover the original
    chunk-local position before adding the chunk's global offset.
    """
    em = chunk.excision_map
    base_sec = chunk.actual_start_ms / 1000.0
    if em is None or em.is_identity:
        return base_sec + local_excised_sec
    orig_local_ms = em.to_original_time_ms(local_excised_sec * 1000.0)
    return base_sec + orig_local_ms / 1000.0


def _globalize_segment(seg: Dict, chunk: AudioChunk) -> Dict:
    """Return a copy of ``seg`` with ``start``/``end`` mapped to global sec."""
    out = dict(seg)
    out['start'] = _excised_local_to_global_sec(seg.get('start', 0.0), chunk)
    out['end'] = _excised_local_to_global_sec(seg.get('end', 0.0), chunk)
    if 'text' in out:
        out['text'] = out['text'].strip() if isinstance(out['text'], str) else out['text']
    return out


def parse_transcription_response(
    response,
    chunk: AudioChunk
) -> Tuple[str, List[Dict], List[WordToken]]:
    """Legacy entry point: parse an OpenAI response then globalise.

    Equivalent to
    ``globalize_chunk_result(*extract_openai_text_and_segments(r), chunk)``.
    """
    text, local_segments = extract_openai_text_and_segments(response)
    chunk_text, segments, words = globalize_chunk_result(text, local_segments, chunk)
    logger.info(f"Chunk {chunk.chunk_index} parsed: {len(chunk_text)} chars, "
                f"{len(segments)} segments, {len(words)} words")
    return chunk_text, segments, words


def _align_words_with_energy_local(
    local_segments: List[Dict],
    chunk: AudioChunk,
    chunk_index: int,
) -> List[WordToken]:
    """
    Silence-aware alignment in excised-local seconds.

    Operates directly on ``chunk.audio_segment`` (the excised audio) using
    the segments' raw API timestamps.  Returns ``WordToken``s whose
    ``start``/``end`` are in **excised-local seconds** — the caller is
    responsible for globalization.
    """
    audio_seg = getattr(chunk, "audio_segment", None)
    if audio_seg is None:
        logger.debug(
            f"Chunk {chunk_index}: no audio_segment on chunk, skipping silence-aware alignment"
        )
        return []

    audio_len_ms = len(audio_seg)
    all_words: List[WordToken] = []

    for seg in local_segments:
        seg_text = seg.get("text", "").strip()
        if not seg_text:
            continue

        seg_start_sec = seg.get("start", 0.0)
        seg_end_sec = seg.get("end", 0.0)
        speaker = seg.get("speaker")
        tokens = tokenize_text(seg_text)
        if not tokens:
            continue

        local_start_ms = int(seg_start_sec * 1000)
        local_end_ms = int(seg_end_sec * 1000)
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
                all_words.append(WordToken(
                    text=wd["word"],
                    start=wd["start_ms"] / 1000.0,
                    end=wd["end_ms"] / 1000.0,
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

