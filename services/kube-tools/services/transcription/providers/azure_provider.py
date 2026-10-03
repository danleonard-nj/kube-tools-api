"""Azure Speech-to-Text provider (Fast Transcription REST API).

Uses the synchronous Fast Transcription endpoint:

    POST https://{region}.api.cognitive.microsoft.com
         /speechtotext/transcriptions:transcribe?api-version={api_version}

Hardened behavior:
- Bounded in-process concurrency
- Retry/backoff for 429 and transient 5xx responses
- Retry-After support
- Per-request timeout
- Better failure diagnostics
- Safer response parsing
"""

import asyncio
import json
import random
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Optional

import httpx2 as httpx
from framework.logger import get_logger

from models.transcription_config import TranscriptionConfig
from services.transcription.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
    Word,
)

logger = get_logger(__name__)

_DEFAULT_API_VERSION = "2025-10-15"
_DEFAULT_TIMEOUT = 300.0
_DEFAULT_MAX_RETRIES = 5
_DEFAULT_INITIAL_BACKOFF_SECONDS = 2.0
_DEFAULT_MAX_BACKOFF_SECONDS = 32.0
_DEFAULT_MAX_CONCURRENCY = 2

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class AzureSpeechProvider(TranscriptionProvider):
    name = "azure"

    def __init__(
        self,
        transcription_config: TranscriptionConfig,
        http_client: httpx.AsyncClient,
    ):
        cfg = transcription_config.kwargs_for("azure")

        self._speech_key = cfg.get("speech_key", "")
        self._region = cfg.get("region", "")
        self._default_language = cfg.get("default_language", "en-US")

        self._api_version = cfg.get("api_version", _DEFAULT_API_VERSION)
        self._timeout = float(cfg.get("timeout_seconds", _DEFAULT_TIMEOUT))

        self._max_retries = int(cfg.get("max_retries", _DEFAULT_MAX_RETRIES))
        self._initial_backoff_seconds = float(
            cfg.get("initial_backoff_seconds", _DEFAULT_INITIAL_BACKOFF_SECONDS)
        )
        self._max_backoff_seconds = float(
            cfg.get("max_backoff_seconds", _DEFAULT_MAX_BACKOFF_SECONDS)
        )

        max_concurrency = int(cfg.get("max_concurrency", _DEFAULT_MAX_CONCURRENCY))
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

        # Optional list of candidate locales for language ID.
        # Falls back to [language or default_language] when not configured.
        self._candidate_locales = cfg.get("candidate_locales") or None

        self._http_client = http_client

        logger.info(
            "AzureSpeechProvider initialized: region=%s api_version=%s "
            "default_language=%s max_concurrency=%s timeout_seconds=%.1f max_retries=%s",
            self._region,
            self._api_version,
            self._default_language,
            max_concurrency,
            self._timeout,
            self._max_retries,
        )

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

        if not audio_bytes:
            raise ValueError("AzureSpeechProvider received empty audio_bytes")

        logger.info(
            "Starting Azure transcription: audio_bytes=%s sample_rate=%s "
            "language=%s diarize=%s",
            len(audio_bytes),
            sample_rate,
            language or self._default_language,
            diarize,
        )

        locales = self._resolve_locales(language)

        definition = self._build_definition(
            locales=locales,
            diarize=diarize,
            prompt=prompt,
        )

        url = (
            f"https://{self._region}.api.cognitive.microsoft.com"
            f"/speechtotext/transcriptions:transcribe?api-version={self._api_version}"
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self._speech_key,
        }

        async with self._semaphore:
            resp = await self._post_with_retries(
                url=url,
                headers=headers,
                audio_bytes=audio_bytes,
                definition=definition,
            )

        logger.info(
            "Azure transcription API response: status=%s request_id=%s",
            resp.status_code,
            _get_header(resp, "x-ms-request-id"),
        )

        if resp.status_code >= 400:
            self._log_failed_response(resp, len(audio_bytes))
            resp.raise_for_status()

        try:
            payload = resp.json()
        except json.JSONDecodeError as ex:
            logger.error(
                "Azure Fast Transcription returned invalid JSON: "
                "status=%s audio_bytes=%s body=%s",
                resp.status_code,
                len(audio_bytes),
                resp.text[:1000],
            )
            raise RuntimeError("Azure Fast Transcription returned invalid JSON") from ex

        return _parse_response(payload, locales[0])

    def _resolve_locales(self, language: Optional[str]) -> list[str]:
        if self._candidate_locales:
            locales = list(self._candidate_locales)
            logger.info(
                "Using candidate locales for language identification: locales=%s",
                locales,
            )
            return locales

        locale = language or self._default_language
        logger.info("Using locale for transcription: locale=%s", locale)
        return [locale]

    def _build_definition(
        self,
        *,
        locales: list[str],
        diarize: bool,
        prompt: Optional[str],
    ) -> dict:
        definition: dict = {
            "locales": locales,
            "profanityFilterMode": "None",
        }

        if diarize:
            definition["diarization"] = {
                "enabled": True,
                "maxSpeakers": 4,
            }

        # Fast transcription's normal mode does not use `prompt` the same way
        # OpenAI-style transcription does. Keep the parameter accepted for
        # interface compatibility, but do not send unsupported fields by default.
        #
        # If you later enable Azure enhancedMode / phraseList, wire it explicitly
        # from config instead of blindly passing arbitrary prompt text.
        if prompt:
            logger.debug(
                "AzureSpeechProvider received prompt, but prompt is not sent "
                "for default Fast Transcription mode."
            )

        return definition

    def _build_files(
        self,
        *,
        audio_bytes: bytes,
        definition: dict,
    ) -> dict:
        # Rebuild files for every retry. This avoids reused/consumed multipart
        # stream weirdness if the HTTP layer ever changes behavior.
        return {
            "audio": ("audio.bin", audio_bytes, "application/octet-stream"),
            "definition": (
                None,
                json.dumps(definition),
                "application/json",
            ),
        }

    async def _post_with_retries(
        self,
        *,
        url: str,
        headers: dict,
        audio_bytes: bytes,
        definition: dict,
    ) -> httpx.Response:
        last_exception: Optional[BaseException] = None
        total_attempts = self._max_retries + 1

        logger.info(
            "Sending transcription request to Azure: url=%s audio_bytes=%s",
            url,
            len(audio_bytes),
        )

        for attempt_index in range(total_attempts):
            attempt_number = attempt_index + 1

            try:
                resp = await self._http_client.post(
                    url,
                    headers=headers,
                    files=self._build_files(
                        audio_bytes=audio_bytes,
                        definition=definition,
                    ),
                    timeout=self._timeout,
                )

                if resp.status_code not in _RETRYABLE_STATUS_CODES:
                    if resp.status_code < 400:
                        logger.info(
                            "Azure transcription request succeeded: "
                            "status=%s request_id=%s attempt=%s/%s",
                            resp.status_code,
                            _get_header(resp, "x-ms-request-id"),
                            attempt_number,
                            total_attempts,
                        )
                    return resp

                if attempt_index >= self._max_retries:
                    return resp

                delay_seconds = self._get_retry_delay_seconds(
                    resp=resp,
                    attempt_index=attempt_index,
                )

                logger.warning(
                    "Azure Fast Transcription transient failure: "
                    "status=%s attempt=%s/%s delay_seconds=%.2f "
                    "audio_bytes=%s request_id=%s body=%s",
                    resp.status_code,
                    attempt_number,
                    total_attempts,
                    delay_seconds,
                    len(audio_bytes),
                    _get_header(resp, "x-ms-request-id"),
                    resp.text[:500],
                )

                await asyncio.sleep(delay_seconds)

            except (
                httpx.TimeoutException,
                httpx.TransportError,
                OSError,
            ) as ex:
                last_exception = ex

                if attempt_index >= self._max_retries:
                    logger.error(
                        "Azure Fast Transcription request failed permanently: "
                        "attempt=%s/%s audio_bytes=%s error=%r",
                        attempt_number,
                        total_attempts,
                        len(audio_bytes),
                        ex,
                    )
                    raise

                delay_seconds = self._get_backoff_delay_seconds(attempt_index)

                logger.warning(
                    "Azure Fast Transcription transport failure: "
                    "attempt=%s/%s delay_seconds=%.2f audio_bytes=%s error=%r",
                    attempt_number,
                    total_attempts,
                    delay_seconds,
                    len(audio_bytes),
                    ex,
                )

                await asyncio.sleep(delay_seconds)

        if last_exception:
            raise last_exception

        raise RuntimeError("Azure Fast Transcription retry loop exited unexpectedly")

    def _get_retry_delay_seconds(
        self,
        *,
        resp: httpx.Response,
        attempt_index: int,
    ) -> float:
        retry_after = resp.headers.get("Retry-After")
        parsed_retry_after = _parse_retry_after_seconds(retry_after)

        if parsed_retry_after is not None:
            return min(parsed_retry_after, self._max_backoff_seconds)

        return self._get_backoff_delay_seconds(attempt_index)

    def _get_backoff_delay_seconds(self, attempt_index: int) -> float:
        base_delay = self._initial_backoff_seconds * (2**attempt_index)
        capped_delay = min(base_delay, self._max_backoff_seconds)

        # Small jitter prevents multiple workers from retrying in lockstep.
        jitter = random.uniform(0.0, 0.5)

        return capped_delay + jitter

    def _log_failed_response(self, resp: httpx.Response, audio_size_bytes: int) -> None:
        logger.error(
            "Azure Fast Transcription failed: "
            "status=%s audio_bytes=%s request_id=%s retry_after=%s "
            "content_type=%s body=%s",
            resp.status_code,
            audio_size_bytes,
            _get_header(resp, "x-ms-request-id"),
            resp.headers.get("Retry-After"),
            resp.headers.get("content-type"),
            resp.text[:1000],
        )


def _parse_retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None

    value = value.strip()

    # Retry-After can be an integer number of seconds.
    try:
        seconds = float(value)
        if seconds >= 0:
            return seconds
    except ValueError:
        pass

    # Or an HTTP date.
    try:
        retry_at = parsedate_to_datetime(value)

        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        seconds = (retry_at - now).total_seconds()

        return max(0.0, seconds)
    except Exception:
        return None


def _get_header(resp: httpx.Response, name: str) -> Optional[str]:
    # httpx headers are case-insensitive, but keep this helper so logging remains tidy.
    return resp.headers.get(name)


def _parse_response(payload: dict, fallback_language: str) -> TranscriptionResult:
    """Convert a Fast Transcription response into a TranscriptionResult."""

    combined = payload.get("combinedPhrases") or []
    text = " ".join((c.get("text") or "").strip() for c in combined).strip()

    phrases = payload.get("phrases") or []
    duration_ms = int(payload.get("durationMilliseconds") or 0)

    logger.info(
        "Parsing Azure transcription response: phrase_count=%s combined_count=%s "
        "duration_ms=%s fallback_language=%s",
        len(phrases),
        len(combined),
        duration_ms,
        fallback_language,
    )

    words: list[Word] = []
    confidences: list[float] = []
    segments: list[dict] = []
    locale = fallback_language

    for ph in phrases:
        confidence = ph.get("confidence")
        if confidence is not None:
            try:
                confidences.append(float(confidence))
            except (TypeError, ValueError):
                logger.debug("Skipping invalid Azure phrase confidence: %r", confidence)

        if ph.get("locale"):
            locale = ph["locale"]

        speaker = ph.get("speaker")
        speaker_str = str(speaker) if speaker is not None else None

        ph_offset_s = _milliseconds_to_seconds(ph.get("offsetMilliseconds"))
        ph_dur_s = _milliseconds_to_seconds(ph.get("durationMilliseconds"))

        segments.append(
            {
                "start": ph_offset_s,
                "end": ph_offset_s + ph_dur_s,
                "text": ph.get("text") or "",
                "speaker": speaker_str,
            }
        )

        for w in ph.get("words") or []:
            start = _milliseconds_to_seconds(w.get("offsetMilliseconds"))
            dur = _milliseconds_to_seconds(w.get("durationMilliseconds"))

            words.append(
                Word(
                    text=w.get("text") or "",
                    start=start,
                    end=start + dur,
                    speaker=speaker_str,
                )
            )

    if not text and phrases:
        text = " ".join((p.get("text") or "").strip() for p in phrases).strip()

    confidence_result = (
        sum(confidences) / len(confidences)
        if confidences
        else None
    )

    if not text:
        logger.warning(
            "Azure Fast Transcription produced empty transcript: "
            "duration_ms=%s phrase_count=%s combined_phrase_count=%s",
            duration_ms,
            len(phrases),
            len(combined),
        )
    else:
        logger.info(
            "Successfully transcribed audio: text_length=%s confidence=%.2f "
            "detected_language=%s word_count=%s segment_count=%s",
            len(text),
            confidence_result or 0.0,
            locale,
            len(words),
            len(segments),
        )

    return TranscriptionResult(
        text=text,
        confidence=confidence_result,
        duration_ms=duration_ms,
        words=words or None,
        segments=segments or None,
        metadata={
            "language": locale,
            "provider": "azure",
        },
    )


def _milliseconds_to_seconds(value: object) -> float:
    try:
        return (float(value or 0)) / 1000.0
    except (TypeError, ValueError):
        return 0.0