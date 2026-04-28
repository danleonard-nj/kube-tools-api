"""OpenAI transcription provider.

Wraps the existing ``client.audio.transcriptions.create`` call and
reuses :func:`extract_openai_text_and_segments` for response parsing.
"""

from typing import Optional

from openai import AsyncOpenAI

from framework.logger import get_logger
from models.transcription_config import TranscriptionConfig
from services.transcription.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
    Word,
)
from services.transcription.response_parsing import extract_openai_text_and_segments

logger = get_logger(__name__)


class OpenAIProvider(TranscriptionProvider):
    name = "openai"

    def __init__(
        self,
        client: AsyncOpenAI,
        transcription_config: TranscriptionConfig,
    ):
        cfg = transcription_config.kwargs_for("openai")
        self._client = client
        self._model = cfg.get("model", "gpt-4o-transcribe")
        self._diarize_model = cfg.get("diarize_model", "gpt-4o-transcribe-diarize")
        self._temperature = float(cfg.get("temperature", 0.0))
        self._export_format = cfg.get("export_format", "flac")

    async def transcribe(
        self,
        audio_bytes: bytes,
        *,
        sample_rate: int,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        diarize: bool = False,
    ) -> TranscriptionResult:
        model = self._diarize_model if diarize else self._model
        response_format = "diarized_json" if diarize else "json"
        mime_type = "audio/flac" if self._export_format == "flac" else "audio/wav"
        filename = f"chunk.{self._export_format}"

        kwargs = {
            "file": (filename, audio_bytes, mime_type),
            "model": model,
            "temperature": self._temperature,
            "response_format": response_format,
        }
        if diarize:
            kwargs["chunking_strategy"] = "auto"
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["prompt"] = prompt

        response = await self._client.audio.transcriptions.create(**kwargs)
        text, segments = extract_openai_text_and_segments(response)

        words = None
        if segments:
            extracted = []
            for seg in segments:
                spk = seg.get("speaker")
                if "words" in seg and isinstance(seg["words"], list):
                    for w in seg["words"]:
                        extracted.append(Word(
                            text=w.get("word", w.get("text", "")),
                            start=float(w.get("start", 0.0)),
                            end=float(w.get("end", 0.0)),
                            speaker=spk,
                        ))
            words = extracted or None

        return TranscriptionResult(
            text=text,
            confidence=None,
            duration_ms=0,  # filled by caller from chunk duration
            words=words,
            segments=segments or None,
            metadata={"model": model, "response_format": response_format},
        )
