"""Transcription service — orchestration layer.

Pipeline:
    raw audio bytes (Redis upload cache) →
    pydub decode → VAD-planned chunks (services.transcription.dsp.pipeline) →
    per-chunk OpenAI ASR → overlap.py seam dedup →
    persist run row to Mongo (services.data.transcription_run_repository).
"""

import io
import time
from datetime import datetime
from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Union

import numpy as np
from openai import AsyncOpenAI
from pydub import AudioSegment
from pydub.effects import normalize as pydub_normalize

from clients.gpt_client import GPTClient
from data.transcription_history_repository import TranscriptionHistoryRepository
from data.transcription_run_repository import TranscriptionRunRepository
from framework.logger import get_logger
from models.openai_config import OpenAIConfig
from models.transcription_config import TranscriptionConfig
from services.transcription import PIPELINE_VERSION
from services.transcription.dsp import get_audio_mime_type, preprocess_for_transcription
from services.transcription.models import (
    AudioChunk, ChunkPlanEntry, PreprocessResult, WordToken,
)
from services.transcription.overlap import (
    deduplicate_seam, trim_segments_in_overlap_window,
    trim_word_tokens_in_overlap_window,
)
from services.transcription.providers import (
    TranscriptionProvider, TranscriptionResult,
)
from services.transcription.providers.azure_provider import AzureSpeechProvider
from services.transcription.providers.google_provider import GoogleSpeechProvider
from services.transcription.providers.openai_provider import OpenAIProvider
from services.transcription.providers.whisper_provider import WhisperProvider
from services.transcription.response_parsing import globalize_chunk_result
from services.transcription.segmentation import (
    format_diarized_transcript, normalize_speaker_labels, resegment_words_to_segments,
)
from utilities.memory import release_memory
from utilities.timing import log_stage_timing

logger = get_logger(__name__)


TAIL_PAD_MS=1500  # Silence to append to the final chunk to help the model finalise decoding

# ── LLM polish layer ──────────────────────────────────────────────────────
DEFAULT_POLISH_MODEL = "gpt-4o-mini"
POLISH_MIN_CHARS = 20  # Skip polish for trivially short transcripts.
POLISH_SYSTEM_PROMPT = """
You are a transcript post-processor.

Your task is to lightly clean a transcript while preserving the original wording and meaning.

STRICT RULES:
- Do NOT rephrase sentences.
- Do NOT change wording unless correcting a clear transcription error.
- Do NOT remove filler words (e.g., "um", "uh", "like") unless they are clearly erroneous duplicates.
- Do NOT summarize or add information.
- Do NOT change tone or style.

ALLOWED CHANGES ONLY:
- Fix punctuation
- Fix capitalization
- Fix obvious transcription errors (misspelled common words, clearly wrong words)
- Split into readable paragraphs

OUTPUT REQUIREMENTS:
- Preserve original wording as much as possible
- Keep sentence structure intact
- Return only the cleaned transcript
"""


class TranscriptionServiceError(Exception):
    """Raised for transcription failures."""


# ---------------------------------------------------------------------------
# Audio statistics (cheap; no DSP, just summaries)
# ---------------------------------------------------------------------------

def _audio_stats(audio: AudioSegment) -> Dict[str, Any]:
    """Return cheap audio summary stats for the run row."""
    sr = audio.frame_rate
    channels = audio.channels
    duration_ms = float(len(audio))

    raw = np.array(audio.get_array_of_samples(), dtype=np.int16)
    if channels > 1:
        raw = raw.reshape(-1, channels).mean(axis=1)
    samples = raw.astype(np.float32) / 32768.0

    # Sliding 100 ms RMS for loudness percentiles.
    win = max(1, int(sr * 0.1))
    if samples.size >= win:
        # Vectorised RMS via cumulative-sum trick.
        sq = samples * samples
        csum = np.concatenate([[0.0], np.cumsum(sq)])
        rms = np.sqrt((csum[win:] - csum[:-win]) / win)
        rms = rms[rms > 1e-6]
    else:
        rms = np.array([], dtype=np.float32)

    if rms.size:
        db = 20.0 * np.log10(rms)
        p10, p50, p90 = (float(np.percentile(db, p)) for p in (10, 50, 90))
        # Crude SNR proxy: top decile loudness − bottom decile loudness.
        estimated_snr_db = float(p90 - p10)
    else:
        p10 = p50 = p90 = -120.0
        estimated_snr_db = 0.0

    return {
        "duration_ms": duration_ms,
        "sample_rate": sr,
        "channels": channels,
        "loudness_p10_db": p10,
        "loudness_p50_db": p50,
        "loudness_p90_db": p90,
        "estimated_snr_db": estimated_snr_db,
    }


def _compress_probs(probs: np.ndarray, max_kb: int = 100) -> List[float]:
    """Downsample VAD probability stream so the JSON list stays under ``max_kb``."""
    arr = np.asarray(probs, dtype=np.float32)
    if arr.size == 0:
        return []
    # Each float ≈ 8 bytes JSON-encoded.  Aim for ≤ max_kb * 1024 bytes.
    max_floats = max(256, (max_kb * 1024) // 8)
    if arr.size <= max_floats:
        return [round(float(v), 4) for v in arr.tolist()]
    factor = int(np.ceil(arr.size / max_floats))
    pad = (-arr.size) % factor
    if pad:
        arr = np.concatenate([arr, np.full(pad, arr[-1], dtype=np.float32)])
    down = arr.reshape(-1, factor).mean(axis=1)
    return [round(float(v), 4) for v in down.tolist()]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class TranscriptionServiceError(Exception):
    """Raised for transcription failures."""


# ---------------------------------------------------------------------------
# Audio statistics (cheap; no DSP, just summaries)
# ---------------------------------------------------------------------------

def _audio_stats(audio: AudioSegment) -> Dict[str, Any]:
    """Return cheap audio summary stats for the run row."""
    sr = audio.frame_rate
    channels = audio.channels
    duration_ms = float(len(audio))

    raw = np.array(audio.get_array_of_samples(), dtype=np.int16)
    if channels > 1:
        raw = raw.reshape(-1, channels).mean(axis=1)
    samples = raw.astype(np.float32) / 32768.0

    # Sliding 100 ms RMS for loudness percentiles.
    win = max(1, int(sr * 0.1))
    if samples.size >= win:
        # Vectorised RMS via cumulative-sum trick.
        sq = samples * samples
        csum = np.concatenate([[0.0], np.cumsum(sq)])
        rms = np.sqrt((csum[win:] - csum[:-win]) / win)
        rms = rms[rms > 1e-6]
    else:
        rms = np.array([], dtype=np.float32)

    if rms.size:
        db = 20.0 * np.log10(rms)
        p10, p50, p90 = (float(np.percentile(db, p)) for p in (10, 50, 90))
        # Crude SNR proxy: top decile loudness − bottom decile loudness.
        estimated_snr_db = float(p90 - p10)
    else:
        p10 = p50 = p90 = -120.0
        estimated_snr_db = 0.0

    return {
        "duration_ms": duration_ms,
        "sample_rate": sr,
        "channels": channels,
        "loudness_p10_db": p10,
        "loudness_p50_db": p50,
        "loudness_p90_db": p90,
        "estimated_snr_db": estimated_snr_db,
    }


def _compress_probs(probs: np.ndarray, max_kb: int = 100) -> List[float]:
    """Downsample VAD probability stream so the JSON list stays under ``max_kb``."""
    arr = np.asarray(probs, dtype=np.float32)
    if arr.size == 0:
        return []
    # Each float ≈ 8 bytes JSON-encoded.  Aim for ≤ max_kb * 1024 bytes.
    max_floats = max(256, (max_kb * 1024) // 8)
    if arr.size <= max_floats:
        return [round(float(v), 4) for v in arr.tolist()]
    factor = int(np.ceil(arr.size / max_floats))
    pad = (-arr.size) % factor
    if pad:
        arr = np.concatenate([arr, np.full(pad, arr[-1], dtype=np.float32)])
    down = arr.reshape(-1, factor).mean(axis=1)
    return [round(float(v), 4) for v in down.tolist()]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class TranscriptionService:
    """Service for handling audio transcription using OpenAI's Whisper model."""

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        openai_config: OpenAIConfig,
        transcription_repository: TranscriptionHistoryRepository,
        transcription_run_repository: TranscriptionRunRepository,
        transcription_config: TranscriptionConfig,
        openai_provider: OpenAIProvider,
        google_provider: GoogleSpeechProvider,
        azure_provider: AzureSpeechProvider,
        whisper_provider: WhisperProvider,
        gpt_client: GPTClient,
    ):
        self._client = openai_client
        self._config = openai_config
        self._repository = transcription_repository
        self._runs = transcription_run_repository
        self._gpt_client = gpt_client
        self._providers: Dict[str, TranscriptionProvider] = {
            "openai": openai_provider,
            "google": google_provider,
            "azure": azure_provider,
            "whisper": whisper_provider,
        }
        self._default_provider_name = (transcription_config.provider or "openai").lower()
        logger.info(
            f"TranscriptionService default provider: {self._default_provider_name}"
        )

    def _get_provider(self, name: Optional[str]) -> TranscriptionProvider:
        key = (name or self._default_provider_name).lower()
        provider = self._providers.get(key)
        if provider is None:
            raise ValueError(
                f"Unknown transcription provider {name!r} "
                f"(supported: {', '.join(sorted(self._providers))})"
            )
        return provider

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def transcribe_audio(
        self,
        audio_file: BinaryIO,
        filename: str,
        upload_id: str,
        language: Optional[str] = None,
        temperature: float = 0.0,
        file_size: Optional[int] = None,
        user_id: Optional[str] = None,
        save_to_history: bool = True,
        diarize: bool = False,
        return_waveform_overlay: bool = False,
        provider_name: Optional[str] = None,
        polish: bool = False,
        polish_model: Optional[str] = None,
        ) -> Dict[str, Any]:
        """Transcribe audio using VAD-planned chunking.

        Args:
            provider_name: Optional override for the speech-to-text
                backend (e.g. ``"openai"``, ``"azure"``, ``"google"``,
                ``"whisper"``). Defaults to the configured provider.

        Returns:
                        Dict payload with ``text`` and ``transcription_id``.
                        Optional keys: ``segments``, ``diarized``, ``waveform_overlay``.
        """
        t0 = time.perf_counter()
        try:
            provider = self._get_provider(provider_name)
            logger.info(
                f"Starting transcription for file: {filename} "
                f"(diarize={diarize}, provider={provider.name})"
            )

            with log_stage_timing(logger, "transcribe_audio.get_mime", fields={"filename": filename}):
                _ = get_audio_mime_type(filename)

            audio_segment = self._decode_audio(audio_file, filename)
            # Compute audio stats once up-front so we can drop the decoded
            # AudioSegment as soon as chunks are materialised.
            audio_stats = _audio_stats(audio_segment)
            audio_ms = float(len(audio_segment))

            # ── DSP: VAD → plan → materialise ──────────────────────────
            with log_stage_timing(
                logger, "transcribe_audio.preprocess",
                fields={"filename": filename, "audio_ms": audio_ms},
            ):
                pre: PreprocessResult = preprocess_for_transcription(
                    audio_segment,
                    debug_tag=filename,
                    return_waveform_overlay=True,
                )
            chunks: List[AudioChunk] = pre.chunks
            chunk_plan: List[ChunkPlanEntry] = pre.chunk_plan
            waveform_overlay = pre.waveform_overlay
            # Free the decoded source AudioSegment — chunks own their own
            # slices, the overlay PNG is already rendered, and stats were
            # captured above.
            audio_segment = None  # type: ignore[assignment]
            pre.audio = None  # type: ignore[assignment]
            logger.info(f"Plan produced {len(chunks)} chunks")

            # ── Transcribe + dedup ─────────────────────────────────────
            raw_text, all_segments, all_words, per_chunk_records = await self._run_chunks(
                chunks=chunks, filename=filename,
                language=language, temperature=temperature, diarize=diarize,
                provider=provider,
            )

            # ── Optional LLM polish (skipped when diarize=True) ────────
            polished_text: Optional[str] = None
            polish_model_used: Optional[str] = None
            if polish and not diarize:
                polished_text, polish_model_used = await self._polish_text(
                    raw_text, polish_model, filename=filename,
                )
            elif polish and diarize:
                logger.info("polish requested but diarize=True; skipping polish pass")

            result_text = polished_text if polished_text else raw_text

            # ── Persist run row ────────────────────────────────────────
            transcription_id = await self._persist_run(
                user_id=user_id, filename=filename, upload_id=upload_id,
                audio_stats=audio_stats, vad_probs=pre.vad_probs,
                chunk_plan=chunk_plan, merged_text=raw_text,
                per_chunk=per_chunk_records,
                polished_text=polished_text,
                polish_model=polish_model_used,
                waveform_overlay=waveform_overlay,
            )

            duration = time.perf_counter() - t0
            logger.info(
                f"Transcription completed: {len(result_text)} chars in {duration:.2f}s "
                f"(id={transcription_id})",
            )

            if save_to_history:
                try:
                    await self._repository.save_transcription(
                        filename=filename, transcribed_text=result_text,
                        language=language, file_size=file_size,
                        duration=duration, user_id=user_id,
                    )
                except Exception as exc:
                    logger.warning(f"history save failed: {exc}")

            return self._build_response(
                result_text=result_text, all_words=all_words, all_segments=all_segments,
                diarize=diarize, waveform_overlay=waveform_overlay,
                return_waveform_overlay=return_waveform_overlay,
                transcription_id=transcription_id,
                raw_text=raw_text,
                polished=polished_text is not None,
                polish_model=polish_model_used,
            )

        except TranscriptionServiceError:
            release_memory()
            raise
        except Exception as e:
            release_memory()
            logger.error(f"Failed to transcribe audio file {filename}: {e}", exc_info=True)
            raise TranscriptionServiceError(f"Failed to transcribe audio file {filename}: {e}") from e

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_audio(audio_file: BinaryIO, filename: str) -> AudioSegment:
        audio_file.seek(0)
        data = audio_file.read()
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        try:
            if ext == "webm":
                return AudioSegment.from_file(io.BytesIO(data), format="webm", codec="opus")
            return AudioSegment.from_file(io.BytesIO(data))
        except Exception as exc:
            raise TranscriptionServiceError(f"Failed to load audio file: {exc}") from exc

    async def _polish_text(
        self,
        text: str,
        polish_model: Optional[str],
        filename: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """Run an LLM cleanup pass over the merged transcript.

        Returns ``(polished_text, model_used)`` on success or
        ``(None, None)`` on failure / skip — callers fall back to the
        raw text in either case so polish never fails the request.
        """
        if not text or len(text.strip()) < POLISH_MIN_CHARS:
            logger.info(
                f"polish skipped: text too short ({len(text.strip())} chars)"
            )
            return None, None

        model = polish_model or DEFAULT_POLISH_MODEL
        try:
            with log_stage_timing(
                logger, "transcribe_audio.polish",
                fields={"filename": filename, "model": model, "chars": len(text)},
            ):
                result = await self._gpt_client.generate_completion(
                    prompt=text,
                    model=model,
                    system_prompt=POLISH_SYSTEM_PROMPT,
                    temperature=0.2,
                    use_cache=False,
                )
            polished = (result.content or "").strip()
            if not polished:
                logger.warning("polish returned empty content; falling back to raw text")
                return None, None
            return polished, model
        except Exception as exc:
            logger.warning(f"polish failed ({model}): {exc}; falling back to raw text")
            return None, None

    async def _run_chunks(
        self,
        chunks: List[AudioChunk],
        filename: str,
        language: Optional[str],
        temperature: float,
        diarize: bool,
        provider: TranscriptionProvider,
    ) -> Tuple[str, List[Dict], List[WordToken], List[Dict[str, Any]]]:
        """Transcribe each chunk, dedup at seams, return merged outputs + per-chunk record."""
        all_segments: List[Dict] = []
        all_texts: List[str] = []
        all_words: List[WordToken] = []
        per_chunk_records: List[Dict[str, Any]] = []

        export_format = "flac"
        last_idx = len(chunks) - 1
        for chunk in chunks:
            is_last = chunk.chunk_index == chunks[last_idx].chunk_index
            with log_stage_timing(
                logger, "transcribe_audio.chunk",
                fields={
                    "chunk_index": chunk.chunk_index, "chunks": len(chunks),
                    "chunk_ms": len(chunk.audio_segment),
                    "provider": provider.name,
                    "is_last": is_last,
                },
            ):
                chunk_text, chunk_segments, chunk_words = await self._transcribe_chunk(
                    chunk, filename, language, temperature, export_format,
                    is_last=is_last, diarize=diarize, provider=provider,
                )
            # Free the per-chunk audio immediately — no downstream consumer
            # needs the raw samples once the API call has completed and the
            # response has been parsed (timestamps were globalised inside
            # parse_transcription_response via the chunk's excision_map).
            chunk.audio_segment = None  # type: ignore[assignment]
            chunk.excision_map = None

            # Drop tokens/segments inside the leading overlap (owned by previous chunk).
            if chunk.chunk_index > 0:
                overlap_end_sec = chunk.logical_start_ms / 1000.0
                if chunk_words:
                    chunk_words = trim_word_tokens_in_overlap_window(chunk_words, overlap_end_sec)
                if chunk_segments:
                    chunk_segments = trim_segments_in_overlap_window(chunk_segments, overlap_end_sec)
                if not chunk_words and not chunk_segments:
                    chunk_text = ""

            # Text-level seam dedup as a safety net for coarse timing.
            if all_texts:
                chunk_text = deduplicate_seam(all_texts[-1], chunk_text)

            words_after_dedup_count = len(chunk_words)
            per_chunk_records.append({
                "chunk_index": chunk.chunk_index,
                "raw_text": chunk_text,
                "words_after_dedup": words_after_dedup_count,
            })

            all_texts.append(chunk_text)
            if chunk_segments:
                if all_segments:
                    prev_text = all_segments[-1].get("text", "")
                    chunk_segments[0]["text"] = deduplicate_seam(prev_text, chunk_segments[0].get("text", ""))
                all_segments.extend(chunk_segments)
            if chunk_words:
                all_words.extend(chunk_words)

        return " ".join(all_texts).strip(), all_segments, all_words, per_chunk_records

    async def _persist_run(
        self,
        user_id: Optional[str],
        filename: str,
        upload_id: str,
        audio_stats: Dict[str, Any],
        vad_probs: Optional[np.ndarray],
        chunk_plan: List[ChunkPlanEntry],
        merged_text: str,
        per_chunk: List[Dict[str, Any]],
        polished_text: Optional[str] = None,
        polish_model: Optional[str] = None,
        waveform_overlay: Optional[str] = None,
    ) -> str:
        transcript_doc: Dict[str, Any] = {
            "merged_text": merged_text,
            "per_chunk": per_chunk,
        }
        if polished_text is not None:
            transcript_doc["polished_text"] = polished_text
            transcript_doc["polish_model"] = polish_model
        document = {
            "created_at": datetime.utcnow(),
            "pipeline_version": PIPELINE_VERSION,
            "user_id": user_id,
            "filename": filename,
            "upload_id": upload_id,
            "audio_stats": audio_stats,
            "vad_probability_stream": _compress_probs(vad_probs) if vad_probs is not None else [],
            "chunk_plan": [e.to_dict() for e in chunk_plan],
            "transcript": transcript_doc,
            "waveform_overlay": waveform_overlay,
            "audio_status": "ephemeral",
            "audio_storage_ref": None,
            "feedback": None,
        }
        return await self._runs.insert_run(document)

    @staticmethod
    def _build_response(
        result_text: str,
        all_words: List[WordToken],
        all_segments: List[Dict],
        diarize: bool,
        waveform_overlay: Optional[str],
        return_waveform_overlay: bool,
        transcription_id: str,
        raw_text: str,
        polished: bool = False,
        polish_model: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "text": result_text,
            "raw_text": raw_text,
            "transcription_id": transcription_id,
        }
        if polished:
            payload["polished"] = True
            payload["polish_model"] = polish_model

        if diarize:
            if all_words:
                resegmented = resegment_words_to_segments(
                    all_words, pause_threshold_ms=250.0,
                    max_segment_ms=1500.0, split_on_punctuation=True,
                )
                normalized_segments = normalize_speaker_labels(resegmented)
            else:
                normalized_segments = normalize_speaker_labels(all_segments)
            diarized_text = format_diarized_transcript(normalized_segments)
            payload["text"] = diarized_text
            payload["segments"] = normalized_segments
            payload["diarized"] = True
            if return_waveform_overlay and waveform_overlay:
                payload["waveform_overlay"] = waveform_overlay
            return payload

        if return_waveform_overlay and waveform_overlay:
            payload["waveform_overlay"] = waveform_overlay
        return payload

    # ------------------------------------------------------------------
    # Per-chunk provider call (provider-agnostic)
    # ------------------------------------------------------------------

    async def _transcribe_chunk(
        self,
        chunk: AudioChunk,
        filename: str,
        language: Optional[str],
        temperature: float,
        export_format: str = "flac",
        is_last: bool = False,
        diarize: bool = False,
        provider: Optional[TranscriptionProvider] = None,
    ) -> Tuple[str, List[Dict], List[WordToken]]:
        if provider is None:
            provider = self._get_provider(None)
        try:
            # ── Pre-export conditioning ────────────────────────────────
            # For the final chunk only, append real digital silence after
            # the speech so the transcriber sees a clear EOS boundary and
            # finalises decoding.  Production ASR systems (Whisper-style)
            # rely on trailing silence as the implicit end-of-utterance
            # cue; the previous "final word lost" failure was the encoder
            # waiting for more audio.
            export_seg = chunk.audio_segment
            tail_pad_ms = 0
            if is_last:
                tail_pad_ms = TAIL_PAD_MS
                export_seg = export_seg + AudioSegment.silent(
                    duration=tail_pad_ms, frame_rate=export_seg.frame_rate,
                )

            chunk_buffer = io.BytesIO()
            export_params = ["-ar", "16000", "-ac", "1"]
            if export_format == "wav":
                export_params.extend(["-acodec", "pcm_s16le"])

            with log_stage_timing(
                logger, "transcribe_chunk.export",
                fields={"chunk_index": chunk.chunk_index, "export": export_format,
                        "chunk_ms": len(export_seg), "tail_pad_ms": tail_pad_ms,
                        "is_last": is_last},
            ):
                export_seg.export(chunk_buffer, format=export_format, parameters=export_params)
            chunk_buffer.seek(0)
            audio_bytes = chunk_buffer.getvalue()
            chunk_buffer.close()

            voiced_ms = float(len(chunk.audio_segment))  # excised → already voice-only
            chunk_ms = float(len(export_seg))

            # ── Provider call ──────────────────────────────────────────
            with log_stage_timing(
                logger, "transcribe_chunk.provider_call",
                fields={"chunk_index": chunk.chunk_index,
                        "provider": provider.name,
                        "diarize": diarize},
            ):
                provider_result: TranscriptionResult = await provider.transcribe(
                    audio_bytes,
                    sample_rate=16000,
                    language=language,
                    diarize=diarize,
                )

            with log_stage_timing(
                logger, "transcribe_chunk.parse_response",
                fields={"chunk_index": chunk.chunk_index},
            ):
                chunk_text, segments, words = globalize_chunk_result(
                    provider_result.text, provider_result.segments, chunk,
                )

            # ── Per-chunk instrumentation (truncation detector) ────────
            voiced_sec = voiced_ms / 1000.0 if voiced_ms else 0.0
            wps = (len(chunk_text.split()) / voiced_sec) if voiced_sec > 0 else 0.0
            logger.info(
                "chunk_transcribed "
                f"provider={provider.name} "
                f"chunk_index={chunk.chunk_index} "
                f"chunk_ms={chunk_ms:.0f} "
                f"voiced_ms={voiced_ms:.0f} "
                f"text_chars={len(chunk_text)} "
                f"text_words={len(chunk_text.split())} "
                f"wps={wps:.2f} "
                f"segments={len(segments)} "
                f"confidence={provider_result.confidence}"
            )
            return chunk_text, segments, words
        except Exception as exc:
            logger.error(
                f"Provider {provider.name} failed on chunk "
                f"{chunk.chunk_index}: {exc}",
                exc_info=True,
            )
            raise
