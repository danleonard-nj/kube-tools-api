"""Local Whisper provider — prefers faster-whisper, falls back to openai/whisper."""

import asyncio
import io
import tempfile
import os
from typing import Optional

from framework.logger import get_logger
from models.transcription_config import TranscriptionConfig
from services.transcription.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
    Word,
)

logger = get_logger(__name__)


class WhisperProvider(TranscriptionProvider):
    name = "whisper"

    def __init__(
        self,
        transcription_config: TranscriptionConfig,
    ):
        cfg = transcription_config.kwargs_for("whisper")
        self._model_size = cfg.get("model_size", "large-v3")
        self._device = cfg.get("device", "auto")
        self._compute_type = cfg.get("compute_type", "auto")
        self._beam_size = int(cfg.get("beam_size", 5))
        self._temperature = float(cfg.get("temperature", 0.0))
        self._backend = None  # "faster" or "openai"
        self._model = None  # Lazy-loaded on first transcribe.

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel  # type: ignore
            self._model = WhisperModel(
                self._model_size, device=self._device, compute_type=self._compute_type,
            )
            self._backend = "faster"
            logger.info(f"WhisperProvider: loaded faster-whisper '{self._model_size}'")
        except ImportError:
            try:
                import whisper  # type: ignore
                self._model = whisper.load_model(self._model_size)
                self._backend = "openai"
                logger.info(f"WhisperProvider: loaded openai-whisper '{self._model_size}'")
            except ImportError as exc:
                raise ImportError(
                    "WhisperProvider requires 'faster-whisper' or 'openai-whisper'. "
                    "Install with: pip install faster-whisper  (preferred)"
                ) from exc

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        diarize: bool = False,
    ) -> TranscriptionResult:
        return await asyncio.to_thread(
            self._sync_transcribe, audio_bytes, language, prompt,
        )

    def _sync_transcribe(
        self,
        audio_bytes: bytes,
        language: Optional[str],
        prompt: Optional[str],
    ) -> TranscriptionResult:
        self._ensure_model()
        # Both backends accept a file path; write to a temp file.
        suffix = ".flac" if audio_bytes[:4] == b"fLaC" else ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            if self._backend == "faster":
                segments_iter, info = self._model.transcribe(
                    tmp_path,
                    beam_size=self._beam_size,
                    temperature=self._temperature,
                    language=language,
                    initial_prompt=prompt,
                    word_timestamps=False,
                )
                texts: list[str] = []
                local_segments: list[dict] = []
                for seg in segments_iter:
                    texts.append(seg.text.strip())
                    local_segments.append({
                        "start": float(seg.start),
                        "end": float(seg.end),
                        "text": seg.text.strip(),
                    })
                text = " ".join(texts).strip()
                duration_ms = int((info.duration or 0.0) * 1000)
                return TranscriptionResult(
                    text=text, duration_ms=duration_ms,
                    segments=local_segments or None,
                    metadata={"backend": "faster-whisper"},
                )
            else:
                result = self._model.transcribe(
                    tmp_path,
                    beam_size=self._beam_size,
                    temperature=self._temperature,
                    language=language,
                    initial_prompt=prompt,
                )
                text = (result.get("text") or "").strip()
                local_segments = [
                    {"start": float(s["start"]), "end": float(s["end"]),
                     "text": s["text"].strip()}
                    for s in result.get("segments", [])
                ]
                return TranscriptionResult(
                    text=text, duration_ms=0,
                    segments=local_segments or None,
                    metadata={"backend": "openai-whisper"},
                )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
