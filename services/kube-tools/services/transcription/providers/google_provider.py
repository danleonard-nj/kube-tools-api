"""Google Cloud Speech-to-Text provider (non-realtime / long-form models)."""

import asyncio
from typing import Any, Optional

from framework.logger import get_logger
from models.transcription_config import TranscriptionConfig

from services.google_auth_service import GoogleAuthService
from services.transcription.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
)

logger = get_logger(__name__)


# Cloud Speech-to-Text requires the cloud-platform scope.
_SPEECH_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


class GoogleSpeechProvider(TranscriptionProvider):
    name = "google"

    def __init__(
        self,
        transcription_config: TranscriptionConfig,
        auth_service: GoogleAuthService,
    ):
        """Google Cloud Speech-to-Text provider.

        Auth resolution order (driven by ``transcription.google`` config):

        1. ``auth_client_name`` — reuses the project-wide refresh-token-backed
           credentials via the injected :class:`GoogleAuthService`.
        2. ``credentials_path`` — service-account JSON on disk.
        3. Application Default Credentials (env / metadata server).
        """
        try:
            from google.cloud import speech  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "GoogleSpeechProvider requires 'google-cloud-speech'. "
                "Install with: pip install google-cloud-speech"
            ) from exc

        cfg = transcription_config.kwargs_for("google")
        self._model = cfg.get("model", "latest_long")
        self._default_language = cfg.get("default_language", "en-US")
        self._credentials_path = cfg.get("credentials_path")
        self._auth_client_name = cfg.get("auth_client_name")
        self._auth_service = auth_service if self._auth_client_name else None
        self._cached_client = None

    async def _get_client(self):
        """Build (and cache) the SpeechClient using the configured auth source."""
        if self._cached_client is not None:
            return self._cached_client
        from google.cloud import speech

        if self._auth_service is not None and self._auth_client_name:
            creds = await self._auth_service.get_credentials(
                self._auth_client_name, _SPEECH_SCOPES,
            )
            self._cached_client = speech.SpeechClient(credentials=creds)
        elif self._credentials_path:
            self._cached_client = speech.SpeechClient.from_service_account_file(
                self._credentials_path,
            )
        else:
            self._cached_client = speech.SpeechClient()
        return self._cached_client

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        diarize: bool = False,
    ) -> TranscriptionResult:
        client = await self._get_client()
        return await asyncio.to_thread(
            self._sync_transcribe,
            client,
            audio_bytes,
            sample_rate,
            language or self._default_language,
        )
        # result = self._sync_transcribe(
        #     client,
        #     audio_bytes,
        #     sample_rate,
        #     language or self._default_language,
        # )
        # return result

    def _sync_transcribe(
        self,
        client,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
    ) -> TranscriptionResult:
        from google.cloud import speech

        # Auto-detect FLAC vs LINEAR16 from the magic bytes.
        if len(audio_bytes) >= 4 and audio_bytes[:4] == b"fLaC":
            encoding = speech.RecognitionConfig.AudioEncoding.FLAC
        elif len(audio_bytes) >= 4 and audio_bytes[:4] == b"RIFF":
            encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16
        else:
            encoding = speech.RecognitionConfig.AudioEncoding.LINEAR16

        config = speech.RecognitionConfig(
            encoding=encoding,
            sample_rate_hertz=sample_rate,
            language_code=language,
            model=self._model,
            enable_automatic_punctuation=True,
            use_enhanced=True,
        )
        audio = speech.RecognitionAudio(content=audio_bytes)
        response = client.recognize(config=config, audio=audio)

        parts: list[str] = []
        confidences: list[float] = []
        for result in response.results:
            if result.alternatives:
                alt = result.alternatives[0]
                parts.append(alt.transcript)
                if alt.confidence:
                    confidences.append(alt.confidence)

        text = " ".join(p.strip() for p in parts).strip()
        avg_conf = sum(confidences) / len(confidences) if confidences else None

        return TranscriptionResult(
            text=text,
            confidence=avg_conf,
            duration_ms=0,
            metadata={"model": self._model, "language": language},
        )
