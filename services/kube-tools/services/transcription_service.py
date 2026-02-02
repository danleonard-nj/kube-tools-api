import os
from typing import BinaryIO, Optional, List, Tuple, Union, Dict
import time
import io
import re
from dataclasses import dataclass

from pydub import AudioSegment
from pydub.silence import detect_silence
from openai.types.audio.transcription_create_response import TranscriptionCreateResponse

from openai import AsyncOpenAI
from framework.logger import get_logger
from models.openai_config import OpenAIConfig
from data.transcription_history_repository import TranscriptionHistoryRepository

logger = get_logger(__name__)


@dataclass
class AudioChunk:
    """
    Represents a chunk of audio data with metadata.

    Attributes:
        audio_segment: The actual audio data for this chunk
        logical_start_ms: Start time of the content (without overlap)
        logical_end_ms: End time of the content (without overlap)
        actual_start_ms: Start time including overlap padding
        actual_end_ms: End time including overlap padding
        chunk_index: Index of this chunk in the sequence
    """
    audio_segment: AudioSegment
    logical_start_ms: float
    logical_end_ms: float
    actual_start_ms: float
    actual_end_ms: float
    chunk_index: int


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


def dedupe_word_tokens(
    prev_words: List[WordToken],
    new_words: List[WordToken],
    time_threshold_sec: float = 0.1
) -> List[WordToken]:
    """
    Deduplicate word tokens at chunk boundaries.

    Because chunks overlap, words in the overlap region can repeat.
    Drop new tokens that appear to be duplicates of recent previous tokens.

    Args:
        prev_words: Previously accumulated word tokens
        new_words: New word tokens from current chunk
        time_threshold_sec: Maximum time gap to consider for deduplication (default 100ms)

    Returns:
        Deduplicated list with overlap tokens removed from new_words
    """
    if not prev_words or not new_words:
        return new_words

    # Look at the last few tokens from prev_words (rolling window)
    window_size = min(20, len(prev_words))
    recent_words = prev_words[-window_size:]

    deduped = []
    for new_word in new_words:
        is_duplicate = False

        # Check if this word overlaps with any recent word
        for prev_word in recent_words:
            # Check time proximity and text match
            time_gap = abs(new_word.start - prev_word.end)
            if time_gap <= time_threshold_sec:
                # Normalize text for comparison
                new_text_norm = new_word.text.strip().lower()
                prev_text_norm = prev_word.text.strip().lower()

                if new_text_norm == prev_text_norm:
                    is_duplicate = True
                    logger.debug(f"Deduplicating word token: '{new_word.text}' at {new_word.start:.2f}s")
                    break

        if not is_duplicate:
            deduped.append(new_word)

    return deduped


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

            # Check speaker change
            if word.speaker != prev_word.speaker and word.speaker is not None:
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


def get_audio_mime_type(filename: str) -> str:
    """Get the appropriate MIME type for audio file based on extension."""
    extension = filename.lower().split('.')[-1] if '.' in filename else ''

    mime_types = {
        'mp3': 'audio/mpeg',
        'mp4': 'audio/mp4',
        'm4a': 'audio/mp4',
        'wav': 'audio/wav',
        'flac': 'audio/flac',
        'ogg': 'audio/ogg',
        'oga': 'audio/ogg',
        'webm': 'audio/webm',
        'mpeg': 'audio/mpeg',
        'mpga': 'audio/mpeg'
    }

    return mime_types.get(extension, 'audio/mpeg')  # Default to mpeg if unknown


def split_on_silence(
    audio_segment: AudioSegment,
    silence_thresh_dbfs: float = -45,
    min_silence_len_ms: int = 600,
    chunk_overlap_ms: int = 250,
    min_chunk_len_ms: int = 1000,
    adaptive_threshold: bool = True
) -> List[AudioChunk]:
    """
    Split audio into chunks based on silence detection using dBFS thresholding.

    This function exists because gpt-4o-transcribe treats long silence as end-of-utterance,
    causing early termination of transcription. By splitting on silence, we ensure each
    chunk is transcribed completely.

    Uses pydub's optimized silence detection with dBFS (decibels relative to full scale)
    threshold for consistent behavior across recordings of varying loudness.

    Args:
        audio_segment: The audio to split
        silence_thresh_dbfs: dBFS threshold for silence (default -45). More negative = quieter required
        min_silence_len_ms: Minimum silence duration to trigger split (default 600ms)
        chunk_overlap_ms: Overlap between chunks to avoid word truncation (default 250ms)
        min_chunk_len_ms: Minimum chunk length (default 1000ms)
        adaptive_threshold: If True, adjust threshold based on audio loudness (default True)

    Returns:
        List of AudioChunk objects with logical and actual timing information
    """
    audio_length_ms = len(audio_segment)

    # Adaptive threshold: for very loud audio, use a higher threshold
    if adaptive_threshold:
        audio_dbfs = audio_segment.dBFS
        adjusted_thresh = max(audio_dbfs - 16, silence_thresh_dbfs)
        logger.info(f"Audio dBFS: {audio_dbfs:.2f}, adjusted silence threshold: {adjusted_thresh:.2f} dBFS")
    else:
        adjusted_thresh = silence_thresh_dbfs

    logger.info(f"Splitting audio on silence (thresh={adjusted_thresh:.2f}dBFS, "
                f"min_silence={min_silence_len_ms}ms, overlap={chunk_overlap_ms}ms, "
                f"audio_length={audio_length_ms}ms)")

    # Use pydub's optimized silence detection
    # Returns list of [start_ms, end_ms] for silent ranges
    silent_ranges = detect_silence(
        audio_segment,
        min_silence_len=min_silence_len_ms,
        silence_thresh=adjusted_thresh
    )

    logger.debug(f"Detected {len(silent_ranges)} silent ranges: {silent_ranges}")

    chunks: List[AudioChunk] = []
    chunk_index = 0
    current_chunk_start = 0

    for silence_start, silence_end in silent_ranges:
        chunk_end = silence_start

        # Ensure minimum chunk length
        if chunk_end - current_chunk_start >= min_chunk_len_ms:
            # Calculate actual bounds with overlap
            actual_start = max(0, current_chunk_start - chunk_overlap_ms)
            actual_end = min(audio_length_ms, chunk_end + chunk_overlap_ms)

            chunk_audio = audio_segment[actual_start:actual_end]

            chunks.append(AudioChunk(
                audio_segment=chunk_audio,
                logical_start_ms=current_chunk_start,
                logical_end_ms=chunk_end,
                actual_start_ms=actual_start,
                actual_end_ms=actual_end,
                chunk_index=chunk_index
            ))

            logger.info(f"Chunk {chunk_index}: logical=[{current_chunk_start}-{chunk_end}]ms "
                        f"actual=[{actual_start}-{actual_end}]ms duration={chunk_end - current_chunk_start}ms")

            chunk_index += 1
            current_chunk_start = silence_end  # Start next chunk after silence

    # Add final chunk if there's remaining audio
    if current_chunk_start < audio_length_ms:
        final_duration = audio_length_ms - current_chunk_start
        if final_duration >= min_chunk_len_ms or len(chunks) == 0:
            actual_start = max(0, current_chunk_start - chunk_overlap_ms)
            chunk_audio = audio_segment[actual_start:]

            chunks.append(AudioChunk(
                audio_segment=chunk_audio,
                logical_start_ms=current_chunk_start,
                logical_end_ms=audio_length_ms,
                actual_start_ms=actual_start,
                actual_end_ms=audio_length_ms,
                chunk_index=chunk_index
            ))

            logger.info(f"Final chunk {chunk_index}: logical=[{current_chunk_start}-{audio_length_ms}]ms "
                        f"actual=[{actual_start}-{audio_length_ms}]ms")

    # If no chunks created (no silence or very short audio), return entire audio
    if not chunks:
        logger.info("No silence detected or audio too short - returning entire audio as single chunk")
        chunks.append(AudioChunk(
            audio_segment=audio_segment,
            logical_start_ms=0,
            logical_end_ms=audio_length_ms,
            actual_start_ms=0,
            actual_end_ms=audio_length_ms,
            chunk_index=0
        ))

    logger.info(f"Created {len(chunks)} chunks from audio")
    return chunks


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


class TranscriptionServiceError(Exception):
    """Exception raised for transcription service errors."""
    pass


class TranscriptionService:
    """Service for handling audio transcription using OpenAI's Whisper model."""

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        openai_config: OpenAIConfig,
        transcription_repository: TranscriptionHistoryRepository
    ):
        """
        Initialize the transcription service.

        Args:
            openai_client: Configured AsyncOpenAI client
            openai_config: OpenAI configuration containing API key
            transcription_repository: Repository for storing transcription history
        """
        self._client = openai_client
        self._config = openai_config
        self._repository = transcription_repository

    async def transcribe_audio(
        self,
        audio_file: BinaryIO,
        filename: str,
        language: Optional[str] = None,
        temperature: float = 0.0,
        file_size: Optional[int] = None,
        user_id: Optional[str] = None,
        save_to_history: bool = True,
        diarize: bool = False
    ) -> Union[str, Dict]:
        """
        Transcribe audio file using OpenAI's Whisper model with silence-aware chunking.

        When diarize=True, extracts speaker labels automatically provided by OpenAI's
        gpt-4o-transcribe model.

        Args:
            audio_file: Binary audio file data
            filename: Original filename (used by OpenAI for format detection)
            language: Optional language code (e.g., 'en', 'es', 'fr')
            temperature: Sampling temperature between 0 and 1 (0=deterministic)
            file_size: Optional size of the audio file in bytes
            user_id: Optional user identifier
            save_to_history: Whether to save the transcription to history (default: True)
            diarize: Whether to return diarized output with speaker labels (default: False)

        Returns:
            If diarize=False: Plain text string
            If diarize=True: Dict with 'text', 'segments', and 'diarized' keys
                segments include 'start', 'end', 'speaker', and 'text' fields

        Raises:
            TranscriptionServiceError: If transcription fails
        """
        start_time = time.time()

        try:
            logger.info(f"Starting transcription for file: {filename} (diarize={diarize})")

            # Validate file size (OpenAI limit is 25MB)
            max_file_size = 25 * 1024 * 1024  # 25MB in bytes
            if file_size and file_size > max_file_size:
                raise TranscriptionServiceError(
                    f"File size ({file_size / (1024*1024):.1f}MB) exceeds maximum allowed size of 25MB"
                )

            # Determine MIME type
            mime_type = get_audio_mime_type(filename)
            logger.info(f"Using MIME type: {mime_type}")

            # Use diarize model when diarization is requested
            model = "gpt-4o-transcribe-diarize" if diarize else "gpt-4o-transcribe"

            # Load audio file
            logger.info("Loading audio file...")
            audio_file.seek(0)
            audio_data = audio_file.read()
            logger.info(f"Read {len(audio_data)} bytes")

            # Parse audio with pydub
            try:
                audio_segment = AudioSegment.from_file(io.BytesIO(audio_data))
                logger.info(f"Audio loaded: {len(audio_segment)}ms, "
                            f"{audio_segment.frame_rate}Hz, "
                            f"{audio_segment.channels}ch, "
                            f"{audio_segment.sample_width}B/sample")
            except Exception as e:
                logger.error(f"Failed to load audio: {e}", exc_info=True)
                raise TranscriptionServiceError(f"Failed to load audio file: {e}")

            # Split audio into chunks based on silence
            # This prevents gpt-4o-transcribe from stopping early on long silences
            chunks = split_on_silence(
                audio_segment,
                silence_thresh_dbfs=-45,
                min_silence_len_ms=600,
                chunk_overlap_ms=250,
                min_chunk_len_ms=1000,
                adaptive_threshold=True
            )

            logger.info(f"Audio split into {len(chunks)} chunk(s)")

            # Transcribe each chunk
            all_segments = []  # Backward compatibility (not used as source of truth when diarize=True)
            all_texts = []     # For plain text accumulation
            all_words = []     # Source of truth for word-level timing

            for chunk in chunks:
                logger.info(f"Transcribing chunk {chunk.chunk_index + 1}/{len(chunks)} "
                            f"(duration: {len(chunk.audio_segment)}ms)")

                # Transcribe chunk - now returns words too
                chunk_text, chunk_segments, chunk_words = await self._transcribe_chunk(
                    chunk, filename, model, language, temperature
                )

                # Deduplicate seam overlap for plain text
                if all_texts:
                    chunk_text = deduplicate_seam(all_texts[-1], chunk_text)

                all_texts.append(chunk_text)

                # Process segments for backward compatibility
                if chunk_segments:
                    # Deduplicate segment text at seams
                    if all_segments:
                        prev_text = all_segments[-1]['text']
                        first_seg_text = chunk_segments[0]['text']
                        deduped = deduplicate_seam(prev_text, first_seg_text)
                        chunk_segments[0]['text'] = deduped

                    all_segments.extend(chunk_segments)

                # Process words (source of truth for diarization)
                if chunk_words:
                    # Deduplicate word overlap at chunk boundaries
                    if all_words:
                        chunk_words = dedupe_word_tokens(all_words, chunk_words)

                    all_words.extend(chunk_words)

            # Combine results
            result_text = ' '.join(all_texts).strip()
            duration = time.time() - start_time

            logger.info(f"Transcription completed: {len(result_text)} chars in {duration:.2f}s")

            # Save to history if requested
            if save_to_history:
                try:
                    await self._repository.save_transcription(
                        filename=filename,
                        transcribed_text=result_text,
                        language=language,
                        file_size=file_size,
                        duration=duration,
                        user_id=user_id
                    )
                    logger.info("Transcription saved to history")
                except Exception as e:
                    logger.warning(f"Failed to save transcription to history: {e}")

            # Return appropriate format
            if diarize:
                # Use word-first resegmentation as source of truth
                if all_words:
                    logger.info(f"Resegmenting {len(all_words)} words into new segments")
                    resegmented = resegment_words_to_segments(
                        all_words,
                        pause_threshold_ms=250.0,
                        max_segment_ms=1500.0,
                        split_on_punctuation=True
                    )
                    logger.info(f"Created {len(resegmented)} resegmented segments from words")

                    # Normalize speaker labels (A, B, C -> Speaker 1, Speaker 2, Speaker 3)
                    normalized_segments = normalize_speaker_labels(resegmented)
                else:
                    # Fallback to segment-based approach if no words available
                    logger.warning("No words available, falling back to segment-based diarization")
                    normalized_segments = normalize_speaker_labels(all_segments)

                # Format readable text with speaker labels
                diarized_text = format_diarized_transcript(normalized_segments)

                return {
                    'text': diarized_text,
                    'segments': normalized_segments,
                    'diarized': True
                }
            else:
                return result_text

        except Exception as e:
            error_msg = f"Failed to transcribe audio file {filename}: {e}"
            logger.error(error_msg, exc_info=True)
            raise TranscriptionServiceError(error_msg) from e

    async def _transcribe_chunk(
        self,
        chunk: AudioChunk,
        filename: str,
        model: str,
        language: Optional[str],
        temperature: float
    ) -> Tuple[str, List[Dict], List[WordToken]]:
        """
        Transcribe a single audio chunk.

        Args:
            chunk: AudioChunk to transcribe
            filename: Base filename for identification
            model: OpenAI model name
            language: Optional language code
            temperature: Sampling temperature

        Returns:
            Tuple of (transcribed_text, segments_list, word_tokens)
            - transcribed_text: Plain text transcription
            - segments_list: Segments for backward compatibility
            - word_tokens: List of WordToken (source of truth for timing)
        """
        try:
            # Export chunk to WAV
            chunk_buffer = io.BytesIO()
            chunk.audio_segment.export(chunk_buffer, format="wav")
            chunk_buffer.seek(0)

            chunk_filename = f"{filename}_chunk_{chunk.chunk_index}.wav"

            # Prepare API request
            # Use diarized_json for diarization (gpt-4o-transcribe-diarize) to get granular segments
            # Use json for regular transcription (gpt-4o-transcribe)
            response_format = "diarized_json" if model == "gpt-4o-transcribe-diarize" else "json"

            kwargs = {
                "file": (chunk_filename, chunk_buffer, "audio/wav"),
                "model": model,
                "temperature": temperature,
                "response_format": response_format
            }

            if language:
                kwargs["language"] = language

            # Call OpenAI API
            response: TranscriptionCreateResponse = await self._client.audio.transcriptions.create(**kwargs)

            logger.info(f"Received transcription response for chunk {chunk.chunk_index}: {response}")

            # Robust response extraction
            # OpenAI response may be string, dict, or object with attributes
            chunk_text = ""
            segments = []
            words = []

            if isinstance(response, str):
                chunk_text = response
                segments = []
            elif hasattr(response, 'text'):
                chunk_text = response.text
                # Check for segments in response
                if hasattr(response, 'segments') and response.segments:
                    # Convert OpenAI segments to our format with corrected timestamps
                    # IMPORTANT: Use actual_start_ms to offset timestamps (not logical_start_ms)
                    offset_sec = chunk.actual_start_ms / 1000.0

                    for seg in response.segments:
                        # Handle both dict and object forms
                        if isinstance(seg, dict):
                            # Start with all fields from OpenAI response
                            seg_dict = dict(seg)
                            seg_start = seg.get('start', 0)
                            seg_end = seg.get('end', 0)
                        else:
                            # Convert Pydantic model to dict properly
                            # Try model_dump() first (Pydantic v2), fall back to dict() (Pydantic v1)
                            if hasattr(seg, 'model_dump'):
                                seg_dict = seg.model_dump()
                            elif hasattr(seg, 'dict'):
                                seg_dict = seg.dict()
                            else:
                                # Last resort: manual extraction of data fields only
                                seg_dict = {
                                    'id': getattr(seg, 'id', None),
                                    'start': getattr(seg, 'start', 0),
                                    'end': getattr(seg, 'end', 0),
                                    'text': getattr(seg, 'text', ''),
                                    'speaker': getattr(seg, 'speaker', None),
                                    'type': getattr(seg, 'type', None)
                                }
                            seg_start = seg_dict.get('start', 0)
                            seg_end = seg_dict.get('end', 0)

                        # Adjust timestamps to account for chunk offset
                        seg_dict['start'] = offset_sec + seg_start
                        seg_dict['end'] = offset_sec + seg_end
                        # Ensure text is stripped
                        if 'text' in seg_dict:
                            seg_dict['text'] = seg_dict['text'].strip()

                        segments.append(seg_dict)
                else:
                    # No segments - create one for the whole chunk
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
                        # Start with all fields from OpenAI response
                        seg_dict = dict(seg)
                        # Adjust timestamps to account for chunk offset
                        seg_dict['start'] = offset_sec + seg.get('start', 0)
                        seg_dict['end'] = offset_sec + seg.get('end', 0)
                        # Ensure text is stripped
                        if 'text' in seg_dict:
                            seg_dict['text'] = seg_dict['text'].strip()
                        segments.append(seg_dict)
            else:
                chunk_text = str(response)
                segments = []

            # Always infer word-level timing from segments (OpenAI doesn't provide word-level data)
            if segments:
                logger.debug(f"Chunk {chunk.chunk_index}: Inferring word timing from {len(segments)} segments")
                words = infer_word_tokens_from_segments(segments)
            else:
                words = []

            logger.info(f"Chunk {chunk.chunk_index} transcribed: {len(chunk_text)} chars, "
                        f"{len(segments)} segments, {len(words)} words")

            return chunk_text.strip(), segments, words

        except Exception as e:
            logger.error(f"Failed to transcribe chunk {chunk.chunk_index}: {e}", exc_info=True)
            raise
