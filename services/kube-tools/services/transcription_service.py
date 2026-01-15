import os
from typing import BinaryIO, Optional
import time

from openai import AsyncOpenAI
from framework.logger import get_logger
from models.openai_config import OpenAIConfig
from data.transcription_history_repository import TranscriptionHistoryRepository

logger = get_logger(__name__)


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


class TranscriptionServiceError(Exception):
    """Exception raised for transcription service errors."""
    pass


class TranscriptionService:
    """Service for handling audio transcription using OpenAI's Whisper model."""

    def __init__(self, openai_client: AsyncOpenAI, openai_config: OpenAIConfig, transcription_repository: TranscriptionHistoryRepository):
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
        save_to_history: bool = True
    ) -> str:
        """
        Transcribe audio file using OpenAI's Whisper model.

        Args:
            audio_file: Binary audio file data
            filename: Original filename (used by OpenAI for format detection)
            language: Optional language code (e.g., 'en', 'es', 'fr')
            temperature: Sampling temperature between 0 and 1 (0 = deterministic)
            file_size: Optional size of the audio file in bytes
            user_id: Optional user identifier
            save_to_history: Whether to save the transcription to history (default: True)

        Returns:
            Transcribed text as a string

        Raises:
            TranscriptionServiceError: If transcription fails
        """
        start_time = time.time()

        try:
            logger.info(f"Starting transcription for file: {filename}")

            # Validate file size (OpenAI limit is 25MB)
            max_file_size = 25 * 1024 * 1024  # 25MB in bytes
            if file_size and file_size > max_file_size:
                raise TranscriptionServiceError(
                    f"File size ({file_size / (1024*1024):.1f}MB) exceeds maximum allowed size of 25MB"
                )

            # Estimate duration based on file size (rough estimation)
            # Typical audio: ~1MB per minute for compressed formats
            if file_size:
                estimated_duration_minutes = file_size / (1024 * 1024)  # Very rough estimate
                max_duration_minutes = 30  # Conservative limit

                if estimated_duration_minutes > max_duration_minutes:
                    logger.warning(
                        f"File size suggests audio may be longer than {max_duration_minutes} minutes. "
                        f"Estimated: {estimated_duration_minutes:.1f} minutes"
                    )

            # Determine the correct MIME type for the file
            mime_type = get_audio_mime_type(filename)
            logger.info(f"Using MIME type: {mime_type} for file: {filename}")

            # Prepare the transcription request
            # Using the new OpenAI SDK pattern for audio transcription
            kwargs = {
                "file": (filename, audio_file, mime_type),  # Format: (filename, file_data, mime_type)
                "model": "whisper-1",
                "temperature": temperature,
                "response_format": "text"  # Return plain text instead of JSON
            }

            # Add language parameter if specified
            if language:
                kwargs["language"] = language

            # Make the transcription request
            transcript = await self._client.audio.transcriptions.create(**kwargs)

            # The response is plain text when response_format="text"
            result_text = transcript.strip() if isinstance(transcript, str) else transcript.text.strip()

            duration = time.time() - start_time
            logger.info(f"Transcription completed. Length: {len(result_text)} characters, Duration: {duration:.2f}s")

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
                    # Don't fail the transcription if saving to history fails
                    logger.warning(f"Failed to save transcription to history: {str(e)}")

            return result_text

        except Exception as e:
            error_msg = f"Failed to transcribe audio file {filename}: {str(e)}"
            logger.error(error_msg)
            raise TranscriptionServiceError(error_msg) from e
