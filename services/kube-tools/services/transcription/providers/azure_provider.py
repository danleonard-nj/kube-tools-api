"""Azure Speech-to-Text provider (Fast Transcription REST API).

Uses the synchronous Fast Transcription endpoint:
    POST https://{region}.api.cognitive.microsoft.com
         /speechtotext/transcriptions:transcribe?api-version=2024-11-15

The endpoint accepts WAV/MP3/FLAC/OGG/Opus directly via multipart upload
and returns word-level timestamps, per-phrase confidence, and optional
diarization — so we don't need the native Speech SDK, PCM transcoding,
or a streaming session.
"""

import json
from typing import Optional

import httpx
from framework.logger import get_logger

from models.transcription_config import TranscriptionConfig
from services.transcription.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
    Word,
)

logger = get_logger(__name__)

_API_VERSION = "2024-11-15"
_DEFAULT_TIMEOUT = 300.0  # seconds; chunks are short, but allow headroom


class AzureSpeechProvider(TranscriptionProvider):
    name = "azure"

    def __init__(
        self,
        transcription_config: TranscriptionConfig,
        http_client: httpx.AsyncClient
    ):
        cfg = transcription_config.kwargs_for("azure")
        self._speech_key = cfg.get("speech_key", "")
        self._region = cfg.get("region", "")
        self._default_language = cfg.get("default_language", "en-US")
        self._timeout = float(cfg.get("timeout_seconds", _DEFAULT_TIMEOUT))
        # Optional list of candidate locales for language ID; falls back
        # to [language or default_language] when not configured.
        self._candidate_locales = cfg.get("candidate_locales") or None
        self._http_client = http_client

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        diarize: bool = False,
    ) -> TranscriptionResult:
        if not self._speech_key or not self._region:
            raise RuntimeError(
                "AzureSpeechProvider missing speech_key/region in transcription_config",
            )

        locales = (
            self._candidate_locales
            if self._candidate_locales
            else [language or self._default_language]
        )

        definition: dict = {
            "locales": locales,
            "profanityFilterMode": "None",
        }
        if diarize:
            definition["diarization"] = {"enabled": True, "maxSpeakers": 4}

        url = (
            f"https://{self._region}.api.cognitive.microsoft.com"
            f"/speechtotext/transcriptions:transcribe?api-version={_API_VERSION}"
        )
        headers = {"Ocp-Apim-Subscription-Key": self._speech_key}
        files = {
            "audio": ("audio.bin", audio_bytes, "application/octet-stream"),
            "definition": (None, json.dumps(definition), "application/json"),
        }

        resp = await self._http_client.post(url, headers=headers, files=files)

        if resp.status_code >= 400:
            logger.error(
                "Azure Fast Transcription failed: status=%s body=%s",
                resp.status_code, resp.text[:500],
            )
            resp.raise_for_status()

        return _parse_response(resp.json(), locales[0])


def _parse_response(payload: dict, fallback_language: str) -> TranscriptionResult:
    """Convert a Fast Transcription response into a `TranscriptionResult`.

    Response shape (abridged):
        {
          "durationMilliseconds": 12345,
          "combinedPhrases": [{"text": "..."}],
          "phrases": [
            {
              "offsetMilliseconds": 0,
              "durationMilliseconds": 1500,
              "text": "...",
              "confidence": 0.93,
              "speaker": 1,
              "locale": "en-US",
              "words": [
                {"text": "hi", "offsetMilliseconds": 0, "durationMilliseconds": 200}
              ]
            }
          ]
        }
    """
    combined = payload.get("combinedPhrases") or []
    text = " ".join((c.get("text") or "").strip() for c in combined).strip()

    phrases = payload.get("phrases") or []
    words: list[Word] = []
    confidences: list[float] = []
    segments: list[dict] = []
    locale = fallback_language

    for ph in phrases:
        if ph.get("confidence") is not None:
            confidences.append(float(ph["confidence"]))
        if ph.get("locale"):
            locale = ph["locale"]

        speaker = ph.get("speaker")
        speaker_str = str(speaker) if speaker is not None else None

        ph_offset_s = (ph.get("offsetMilliseconds") or 0) / 1000.0
        ph_dur_s = (ph.get("durationMilliseconds") or 0) / 1000.0
        segments.append({
            "start": ph_offset_s,
            "end": ph_offset_s + ph_dur_s,
            "text": ph.get("text") or "",
            "speaker": speaker_str,
        })

        for w in ph.get("words") or []:
            start = (w.get("offsetMilliseconds") or 0) / 1000.0
            dur = (w.get("durationMilliseconds") or 0) / 1000.0
            words.append(Word(
                text=w.get("text") or "",
                start=start,
                end=start + dur,
                speaker=speaker_str,
            ))

    if not text and phrases:
        # Fall back to concatenating phrase texts if combinedPhrases was empty.
        text = " ".join((p.get("text") or "").strip() for p in phrases).strip()

    confidence = (sum(confidences) / len(confidences)) if confidences else None
    duration_ms = int(payload.get("durationMilliseconds") or 0)

    if not text:
        logger.warning(
            "Azure Fast Transcription produced empty transcript (duration=%dms)",
            duration_ms,
        )

    return TranscriptionResult(
        text=text,
        confidence=confidence,
        duration_ms=duration_ms,
        words=words or None,
        segments=segments or None,
        metadata={"language": locale},
    )
