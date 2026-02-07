"""Word tokenization, word→segment resegmentation, speaker normalization, formatting."""

from typing import Optional, List, Dict

from services.transcription.models import WordToken


def tokenize_text(text: str) -> List[str]:
    """
    Tokenize text into words while preserving punctuation reasonably.

    Split on whitespace but keep punctuation attached to words.

    Args:
        text: Text to tokenize

    Returns:
        List of word tokens
    """
    # Split on whitespace, keep everything else
    tokens = text.split()
    return [t for t in tokens if t.strip()]


def infer_word_tokens_from_segments(
    segments: List[Dict],
    min_duration_sec: float = 0.04
) -> List[WordToken]:
    """
    Infer word-level timing from segment-level data.

    When OpenAI doesn't provide word-level timing, distribute segment
    duration across words proportionally by character length.

    Args:
        segments: List of segment dicts with 'start', 'end', 'text', and optional 'speaker'
        min_duration_sec: Minimum duration per word (default 40ms)

    Returns:
        List of WordToken objects with inferred timing
    """
    words: List[WordToken] = []

    for seg in segments:
        seg_text = seg.get('text', '').strip()
        if not seg_text:
            continue

        seg_start = seg.get('start', 0.0)
        seg_end = seg.get('end', 0.0)
        seg_duration = seg_end - seg_start
        speaker = seg.get('speaker')

        # Tokenize segment text
        tokens = tokenize_text(seg_text)
        if not tokens:
            continue

        # Calculate character lengths for proportional distribution
        token_lengths = [len(t) for t in tokens]
        total_chars = sum(token_lengths)

        if total_chars == 0:
            # Fallback: equal distribution
            word_duration = max(seg_duration / len(tokens), min_duration_sec)
            current_time = seg_start
            for token in tokens:
                words.append(WordToken(
                    text=token,
                    start=current_time,
                    end=current_time + word_duration,
                    speaker=speaker
                ))
                current_time += word_duration
        else:
            # Proportional distribution by character count
            current_time = seg_start
            for i, token in enumerate(tokens):
                # Calculate duration based on character proportion
                char_ratio = token_lengths[i] / total_chars
                word_duration = max(seg_duration * char_ratio, min_duration_sec)

                # For last token, extend to segment end to avoid rounding errors
                if i == len(tokens) - 1:
                    word_end = seg_end
                else:
                    word_end = min(current_time + word_duration, seg_end)

                words.append(WordToken(
                    text=token,
                    start=current_time,
                    end=word_end,
                    speaker=speaker
                ))

                current_time = word_end

    return words


def resegment_words_to_segments(
    words: List[WordToken],
    pause_threshold_ms: float = 250.0,
    max_segment_ms: float = 1500.0,
    split_on_punctuation: bool = True
) -> List[Dict]:
    """
    Create segments from word tokens using word-first resegmentation logic.

    Creates new segments by:
    - Speaker changes
    - Pauses between words >= pause_threshold_ms
    - Duration exceeding max_segment_ms
    - Optionally strong punctuation boundaries (., ?, !, newline)

    Args:
        words: List of WordToken objects (source of truth)
        pause_threshold_ms: Minimum pause to trigger segment split (default 250ms)
        max_segment_ms: Maximum segment duration before forced split (default 1500ms)
        split_on_punctuation: Whether to split on strong punctuation (default True)

    Returns:
        List of segment dicts with 'start', 'end', 'text', and 'speaker' fields
    """
    if not words:
        return []

    pause_threshold_sec = pause_threshold_ms / 1000.0
    max_segment_sec = max_segment_ms / 1000.0

    segments = []
    current_segment_words: List[WordToken] = []
    current_segment_start = None

    def flush_segment():
        """Flush current segment to segments list."""
        nonlocal current_segment_words, current_segment_start

        if not current_segment_words:
            return

        # Calculate segment bounds
        seg_start = current_segment_words[0].start
        seg_end = current_segment_words[-1].end
        seg_text = ' '.join(w.text for w in current_segment_words)

        # Determine speaker by majority vote
        speaker_votes = {}
        for w in current_segment_words:
            if w.speaker:
                speaker_votes[w.speaker] = speaker_votes.get(w.speaker, 0) + 1

        if speaker_votes:
            majority_speaker = max(speaker_votes, key=speaker_votes.get)
        else:
            majority_speaker = None

        segments.append({
            'start': seg_start,
            'end': seg_end,
            'text': seg_text.strip(),
            'speaker': majority_speaker
        })

        current_segment_words = []
        current_segment_start = None

    for i, word in enumerate(words):
        should_split = False

        if current_segment_words:
            prev_word = current_segment_words[-1]

            # Check speaker change — split if labels differ and at
            # least one side is labelled (prevents smearing a labelled
            # speaker across subsequent unlabelled words).
            if word.speaker != prev_word.speaker:
                if word.speaker is not None or prev_word.speaker is not None:
                    should_split = True

            # Check pause threshold
            pause_duration = word.start - prev_word.end
            if pause_duration >= pause_threshold_sec:
                should_split = True

            # Check max duration
            if current_segment_start is not None:
                current_duration = word.end - current_segment_start
                if current_duration >= max_segment_sec:
                    should_split = True

            # Check punctuation
            if split_on_punctuation and prev_word.text.rstrip().endswith(('.', '?', '!')):
                should_split = True

        if should_split:
            flush_segment()

        # Add word to current segment
        if not current_segment_words:
            current_segment_start = word.start
        current_segment_words.append(word)

    # Flush final segment
    flush_segment()

    return segments


def normalize_speaker_labels(segments: List[Dict]) -> List[Dict]:
    """
    Normalize speaker labels from OpenAI (A, B, C, etc.) to Speaker 1, Speaker 2, etc.

    Maintains consistent speaker numbering across all segments.

    Args:
        segments: List of segments with 'speaker' field (from OpenAI)

    Returns:
        Segments with normalized speaker labels
    """
    speaker_map = {}
    next_speaker_num = 1

    for seg in segments:
        if 'speaker' in seg:
            original_speaker = seg['speaker']
            if original_speaker not in speaker_map:
                speaker_map[original_speaker] = f"Speaker {next_speaker_num}"
                next_speaker_num += 1
            seg['speaker'] = speaker_map[original_speaker]

    return segments


def format_diarized_transcript(segments: List[Dict]) -> str:
    """
    Format segments with speaker labels into readable transcript.

    Merges adjacent segments from the same speaker.

    Args:
        segments: List with 'speaker' and 'text' fields

    Returns:
        Formatted transcript with speaker labels
    """
    if not segments:
        return ""

    lines = []
    current_speaker = None
    current_texts = []

    for seg in segments:
        speaker = seg.get('speaker', 'Unknown')
        text = seg.get('text', '').strip()

        if not text:
            continue

        if speaker != current_speaker:
            # Speaker changed - emit previous speaker's text
            if current_speaker and current_texts:
                lines.append(f"{current_speaker}: {' '.join(current_texts)}")
            current_speaker = speaker
            current_texts = [text]
        else:
            current_texts.append(text)

    # Emit final speaker
    if current_speaker and current_texts:
        lines.append(f"{current_speaker}: {' '.join(current_texts)}")

    return '\n'.join(lines)
