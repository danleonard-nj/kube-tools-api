"""Azure Speech-to-Text provider.

Uses the Azure Speech SDK in continuous-recognition mode against a
PushAudioInputStream.  Incoming audio (WAV/FLAC/MP3/raw) is decoded
to 16-bit mono PCM before being pushed, since the SDK's PCM stream
path does not understand container formats without GStreamer.

SDK is imported lazily so the dependency is optional.
"""

import asyncio
import io
import wave
from typing import Optional

from framework.logger import get_logger
from models.transcription_config import TranscriptionConfig
from services.transcription.providers.base import (
    TranscriptionProvider,
    TranscriptionResult,
)

logger = get_logger(__name__)


class AzureSpeechProvider(TranscriptionProvider):
    name = "azure"

    def __init__(
        self,
        transcription_config: TranscriptionConfig,
    ):
        cfg = transcription_config.kwargs_for("azure")
        try:
            import azure.cognitiveservices.speech as speechsdk  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "AzureSpeechProvider requires 'azure-cognitiveservices-speech'. "
                "Install with: pip install azure-cognitiveservices-speech"
            ) from exc

        self._speech_key = cfg.get("speech_key", "")
        self._region = cfg.get("region", "")
        self._default_language = cfg.get("default_language", "en-US")

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
            self._sync_transcribe,
            audio_bytes,
            sample_rate,
            language or self._default_language,
        )

    def _sync_transcribe(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        language: str,
    ) -> TranscriptionResult:
        import threading
        import azure.cognitiveservices.speech as speechsdk

        if not self._speech_key or not self._region:
            raise RuntimeError(
                "AzureSpeechProvider missing speech_key/region in transcription_config",
            )

        # PushAudioInputStream expects raw PCM 16-bit mono.  Strip WAV header
        # if present; otherwise assume the caller already gave us PCM.
        pcm_bytes, sr = _ensure_pcm16_mono(audio_bytes, sample_rate)

        speech_config = speechsdk.SpeechConfig(
            subscription=self._speech_key, region=self._region,
        )
        speech_config.speech_recognition_language = language
        # Detailed output gives us NBest + confidence and surfaces NoMatch reasons.
        speech_config.output_format = speechsdk.OutputFormat.Detailed

        stream_format = speechsdk.audio.AudioStreamFormat(
            samples_per_second=sr, bits_per_sample=16, channels=1,
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_format)
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)
        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=audio_config,
        )

        collected: list[str] = []
        cancel_info: dict = {}
        done_evt = threading.Event()

        def _on_recognized(evt):
            r = evt.result
            if r.reason == speechsdk.ResultReason.RecognizedSpeech and r.text:
                collected.append(r.text)
            elif r.reason == speechsdk.ResultReason.NoMatch:
                logger.debug("Azure STT NoMatch: %s", r.no_match_details)

        def _on_session_stopped(_evt):
            done_evt.set()

        def _on_canceled(evt):
            d = evt.cancellation_details
            cancel_info["reason"] = str(d.reason)
            cancel_info["error_details"] = d.error_details
            if d.reason == speechsdk.CancellationReason.Error:
                logger.error(
                    "Azure STT canceled: reason=%s error=%s",
                    d.reason, d.error_details,
                )
            done_evt.set()

        recognizer.recognized.connect(_on_recognized)
        recognizer.session_stopped.connect(_on_session_stopped)
        recognizer.canceled.connect(_on_canceled)

        recognizer.start_continuous_recognition()
        try:
            # Push in reasonable chunks so the SDK can stream to the service
            # while we're still feeding it.
            chunk_size = 32 * 1024
            for i in range(0, len(pcm_bytes), chunk_size):
                push_stream.write(pcm_bytes[i:i + chunk_size])
            push_stream.close()
            if not done_evt.wait(timeout=120):
                logger.warning("Azure STT timed out waiting for session_stopped")
        finally:
            recognizer.stop_continuous_recognition()

        text = " ".join(collected).strip()
        duration_ms = int(len(pcm_bytes) / (sr * 2) * 1000)
        if not text:
            logger.warning(
                "Azure STT produced empty transcript (duration=%dms, cancel=%s)",
                duration_ms, cancel_info or "n/a",
            )
        return TranscriptionResult(
            text=text,
            confidence=None,
            duration_ms=duration_ms,
            metadata={
                "language": language,
                "region": self._region,
                **({"cancellation": cancel_info} if cancel_info else {}),
            },
        )


def _ensure_pcm16_mono(audio_bytes: bytes, sample_rate: int) -> tuple[bytes, int]:
    """Return (raw_pcm_s16le_mono_bytes, sample_rate).

    Handles WAV via stdlib `wave`; falls back to pydub (ffmpeg) for
    anything else (FLAC, MP3, OGG, ...).  Raw PCM input is passed
    through unchanged with the supplied sample_rate.
    """
    # Fast path: WAV
    if len(audio_bytes) >= 12 and audio_bytes[:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE":
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            if wf.getnchannels() == 1 and wf.getsampwidth() == 2:
                return frames, wf.getframerate()
        # Channel/width mismatch → fall through to pydub re-encode.

    # Detect other known container magic bytes and route through pydub.
    head = audio_bytes[:4]
    is_container = (
        head == b"fLaC"          # FLAC
        or head[:3] == b"ID3"    # MP3 with ID3
        or head == b"OggS"       # OGG
        or head == b"RIFF"       # WAV that failed the mono/16-bit check
        or (len(audio_bytes) > 1 and audio_bytes[0] == 0xFF and (audio_bytes[1] & 0xE0) == 0xE0)  # MP3 frame sync
    )
    if not is_container:
        return audio_bytes, sample_rate

    try:
        from pydub import AudioSegment  # local import; heavy
    except ImportError as exc:
        raise RuntimeError(
            "Azure provider received non-PCM audio but pydub is not installed; "
            "cannot decode to PCM.",
        ) from exc

    seg = AudioSegment.from_file(io.BytesIO(audio_bytes))
    seg = seg.set_channels(1).set_sample_width(2).set_frame_rate(16000)
    return seg.raw_data, seg.frame_rate
