"""
Transcription service — orchestration layer.

All DSP, chunking, overlap-trimming, segmentation, and response-parsing
logic lives in the ``services.transcription`` sub-package.  This module
wires them together behind the public ``TranscriptionService`` class.
"""

import io
import time
from typing import BinaryIO, Optional, List, Tuple, Union, Dict

from pydub import AudioSegment
from openai import AsyncOpenAI

from framework.logger import get_logger
from models.openai_config import OpenAIConfig
from data.transcription_history_repository import TranscriptionHistoryRepository

# --- Sub-module imports (pure functions / data classes) ---------------
from services.transcription.models import AudioChunk, WordToken
from services.transcription.audio_dsp import (
    get_audio_mime_type,
    inject_comfort_noise,
    is_single_shot_safe,
)
from services.transcription.chunking import chunk_by_duration
from services.transcription.overlap import (
    trim_word_tokens_in_overlap_window,
    trim_segments_in_overlap_window,
    deduplicate_seam,
)
from services.transcription.segmentation import (
    resegment_words_to_segments,
    normalize_speaker_labels,
    format_diarized_transcript,
)
from services.transcription.response_parsing import parse_transcription_response

logger = get_logger(__name__)


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
            # Extract file extension for explicit format specification (critical for WebM)
            file_extension = filename.lower().split('.')[-1] if '.' in filename else ''

            try:
                # Explicitly specify format for WebM files to ensure proper Opus decoding
                if file_extension == 'webm':
                    audio_segment = AudioSegment.from_file(
                        io.BytesIO(audio_data),
                        format='webm',
                        codec='opus'  # WebM from browsers typically uses Opus codec
                    )
                else:
                    audio_segment = AudioSegment.from_file(io.BytesIO(audio_data))

                logger.info(f"Audio loaded: {len(audio_segment)}ms, "
                            f"{audio_segment.frame_rate}Hz, "
                            f"{audio_segment.channels}ch, "
                            f"{audio_segment.sample_width}B/sample")
            except Exception as e:
                logger.error(f"Failed to load audio: {e}", exc_info=True)
                raise TranscriptionServiceError(f"Failed to load audio file: {e}")

            # Two-path transcription strategy:
            # Path A: Single-shot with comfort noise (preferred, faster, more accurate)
            # Path B: Duration-based chunking (fallback for large files)

            # Determine which path to use (file_extension already extracted above)
            safe_for_single_shot, export_format = is_single_shot_safe(audio_segment, source_format=file_extension)

            if safe_for_single_shot:
                # PATH A: Single-shot transcription with comfort noise
                logger.info("Using Path A: Single-shot transcription with comfort noise")

                # Inject comfort noise into long silences to keep encoder alive
                audio_segment = inject_comfort_noise(
                    audio_segment,
                    noise_level_db=-60,
                    silence_thresh_dbfs=-42,
                    min_silence_ms=1500,
                    true_silence_dbfs=-55,
                    grace_ms=400,
                    tail_ms=300
                )

                logger.info(f"Transcribing full audio (duration: {len(audio_segment)}ms, format: {export_format})")

                # Create a single chunk for the entire audio
                full_audio_chunk = AudioChunk(
                    audio_segment=audio_segment,
                    logical_start_ms=0,
                    logical_end_ms=len(audio_segment),
                    actual_start_ms=0,
                    actual_end_ms=len(audio_segment),
                    chunk_index=0
                )

                # Transcribe with specified format
                result_text, all_segments, all_words = await self._transcribe_chunk(
                    full_audio_chunk, filename, model, language, temperature, export_format
                )
            else:
                # PATH B: Duration-based chunking fallback
                logger.info("Using Path B: Duration-based chunking (file too large for single-shot)")

                overlap_ms = 1_500
                chunks = chunk_by_duration(
                    audio_segment,
                    chunk_duration_ms=60_000,
                    overlap_ms=overlap_ms
                )

                logger.info(f"Audio split into {len(chunks)} chunks")

                # Transcribe each chunk
                all_segments: List[Dict] = []
                all_texts: List[str] = []
                all_words: List[WordToken] = []

                # Use the same export format determined earlier (WAV for WebM, FLAC otherwise)
                chunk_export_format = export_format

                for chunk in chunks:
                    logger.info(f"Transcribing chunk {chunk.chunk_index + 1}/{len(chunks)} "
                                f"(duration: {len(chunk.audio_segment)}ms)")

                    chunk_text, chunk_segments, chunk_words = await self._transcribe_chunk(
                        chunk, filename, model, language, temperature, chunk_export_format
                    )

                    # --- Deterministic time-based overlap trimming ---
                    # The overlap region [actual_start, logical_start) belongs
                    # to the PREVIOUS chunk.  Compute boundary directly from
                    # logical_start so intent is obvious to future readers.
                    if chunk.chunk_index > 0 and overlap_ms > 0:
                        overlap_end_sec = chunk.logical_start_ms / 1000.0

                        if chunk_words:
                            chunk_words = trim_word_tokens_in_overlap_window(
                                chunk_words, overlap_end_sec
                            )
                        if chunk_segments:
                            chunk_segments = trim_segments_in_overlap_window(
                                chunk_segments, overlap_end_sec
                            )

                    # If trimming removed everything the model returned for
                    # this chunk, blank out chunk_text to avoid phantom
                    # duplicates from coarse timing.
                    if chunk.chunk_index > 0 and not chunk_words and not chunk_segments:
                        logger.info(f"Chunk {chunk.chunk_index}: all tokens/segments fell in overlap, dropping text")
                        chunk_text = ""

                    # Text-level deduplicate_seam as fallback for the first
                    # segment boundary (covers edge cases where timing is
                    # unavailable or imprecise).
                    if all_texts:
                        chunk_text = deduplicate_seam(all_texts[-1], chunk_text)

                    all_texts.append(chunk_text)

                    if chunk_segments:
                        if all_segments:
                            prev_text = all_segments[-1].get('text', '')
                            first_seg_text = chunk_segments[0].get('text', '')
                            deduped = deduplicate_seam(prev_text, first_seg_text)
                            chunk_segments[0]['text'] = deduped
                        all_segments.extend(chunk_segments)

                    if chunk_words:
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
        temperature: float,
        export_format: str = 'flac'
    ) -> Tuple[str, List[Dict], List[WordToken]]:
        """
        Transcribe a single audio chunk.

        This method handles the OpenAI API call; response parsing and
        timestamp offsetting are delegated to ``parse_transcription_response``.

        Args:
            chunk: AudioChunk to transcribe
            filename: Base filename for identification
            model: OpenAI model name
            language: Optional language code
            temperature: Sampling temperature
            export_format: Format to export audio ('flac' or 'wav', default 'flac')

        Returns:
            Tuple of (transcribed_text, segments_list, word_tokens)
            - transcribed_text: Plain text transcription
            - segments_list: Segments for backward compatibility
            - word_tokens: List of WordToken (source of truth for timing)
        """
        try:
            # Export chunk to specified format (prefer FLAC for size)
            chunk_buffer = io.BytesIO()

            # Build export parameters - explicit codec ensures proper encoding
            export_params = ["-ar", "16000", "-ac", "1"]  # 16kHz mono
            if export_format == 'wav':
                # Force PCM encoding for WAV to avoid codec issues
                export_params.extend(["-acodec", "pcm_s16le"])  # 16-bit PCM little-endian

            chunk.audio_segment.export(
                chunk_buffer,
                format=export_format,
                parameters=export_params
            )
            chunk_buffer.seek(0)

            # Get bytes to ensure buffer is properly read
            audio_bytes = chunk_buffer.getvalue()

            # Validate that we have actual audio data
            if len(audio_bytes) < 1000:  # Less than 1KB is suspicious
                logger.warning(f"Export produced only {len(audio_bytes)} bytes for {len(chunk.audio_segment)}ms audio")

            logger.debug(f"Exported {len(audio_bytes)} bytes of {export_format.upper()} audio for chunk {chunk.chunk_index}")

            chunk_filename = f"{filename}_chunk_{chunk.chunk_index}.{export_format}"

            # Determine MIME type
            mime_type = 'audio/flac' if export_format == 'flac' else 'audio/wav'

            # Prepare API request
            # Use diarized_json for diarization (gpt-4o-transcribe-diarize) to get granular segments
            # Use json for regular transcription (gpt-4o-transcribe)
            response_format = "diarized_json" if model == "gpt-4o-transcribe-diarize" else "json"

            # Use the audio bytes directly to avoid any cursor issues
            kwargs = {
                "file": (chunk_filename, audio_bytes, mime_type),
                "model": model,
                "temperature": temperature,
                "response_format": response_format
            }

            # Add chunking_strategy for diarization models (required parameter)
            if model == "gpt-4o-transcribe-diarize":
                kwargs["chunking_strategy"] = "auto"

            if language:
                kwargs["language"] = language

            # Call OpenAI API
            response = await self._client.audio.transcriptions.create(**kwargs)

            logger.info(f"Received transcription response for chunk {chunk.chunk_index}")

            # Delegate response parsing to pure function
            chunk_text, segments, words = parse_transcription_response(response, chunk)

            return chunk_text, segments, words

        except Exception as e:
            logger.error(f"Failed to transcribe chunk {chunk.chunk_index}: {e}", exc_info=True)
            raise
