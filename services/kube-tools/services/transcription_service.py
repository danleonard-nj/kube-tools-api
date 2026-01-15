import os
from typing import BinaryIO, Optional

from openai import AsyncOpenAI
from framework.logger import get_logger
from models.openai_config import OpenAIConfig

logger = get_logger(__name__)


class TranscriptionServiceError(Exception):
    """Exception raised for transcription service errors."""
    pass


class TranscriptionService:
    """Service for handling audio transcription using OpenAI's Whisper model."""

    def __init__(self, openai_client: AsyncOpenAI, openai_config: OpenAIConfig):
        """
        Initialize the transcription service.

        Args:
            openai_client: Configured AsyncOpenAI client
            openai_config: OpenAI configuration containing API key
        """
        self._client = openai_client
        self._config = openai_config

    async def transcribe_audio(
        self,
        audio_file: BinaryIO,
        filename: str,
        language: Optional[str] = None,
        temperature: float = 0.0
    ) -> str:
        """
        Transcribe audio file using OpenAI's Whisper model.

        Args:
            audio_file: Binary audio file data
            filename: Original filename (used by OpenAI for format detection)
            language: Optional language code (e.g., 'en', 'es', 'fr')
            temperature: Sampling temperature between 0 and 1 (0 = deterministic)

        Returns:
            Transcribed text as a string

        Raises:
            TranscriptionServiceError: If transcription fails
        """
        try:
            logger.info(f"Starting transcription for file: {filename}")

            # Prepare the transcription request
            # Using the new OpenAI SDK pattern for audio transcription
            kwargs = {
                "file": (filename, audio_file, "audio/mpeg"),  # Format: (filename, file_data, mime_type)
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

            logger.info(f"Transcription completed. Length: {len(result_text)} characters")
            return result_text

        except Exception as e:
            error_msg = f"Failed to transcribe audio file {filename}: {str(e)}"
            logger.error(error_msg)
            raise TranscriptionServiceError(error_msg) from e
