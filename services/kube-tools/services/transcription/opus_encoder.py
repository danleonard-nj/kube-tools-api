"""ffmpeg → libopus encoder for the transcription archive worker.

We invoke ffmpeg as a subprocess piping bytes in and out so we never
touch disk.  Settings target speech archival, not music: 16 kHz mono at
~16 kbps with the ``voip`` application profile.  At those settings an
hour of audio is roughly 7 MB, intelligible enough to QA transcripts
months later.
"""

from __future__ import annotations

import asyncio
from typing import Optional


DEFAULT_BITRATE_KBPS = 16
DEFAULT_SAMPLE_RATE = 16000
CONTENT_TYPE = "audio/ogg; codecs=opus"
CODEC = "opus"
FILE_EXT = "ogg"


class OpusEncodeError(RuntimeError):
    pass


async def encode_opus(
    audio_bytes: bytes,
    bitrate_kbps: int = DEFAULT_BITRATE_KBPS,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    timeout_seconds: float = 120.0,
) -> bytes:
    """Encode arbitrary input audio bytes to mono Opus in an Ogg container.

    Raises ``OpusEncodeError`` on non-zero ffmpeg exit or timeout.
    """
    if not audio_bytes:
        raise OpusEncodeError("empty input")

    args = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-i", "pipe:0",
        "-vn",
        "-ac", "1",
        "-ar", str(sample_rate),
        "-c:a", "libopus",
        "-b:a", f"{bitrate_kbps}k",
        "-application", "voip",
        "-f", "ogg",
        "pipe:1",
    ]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=audio_bytes),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise OpusEncodeError(f"ffmpeg timed out after {timeout_seconds}s")

    if proc.returncode != 0:
        err_tail: Optional[str] = None
        if stderr:
            err_tail = stderr.decode("utf-8", errors="replace")[-500:]
        raise OpusEncodeError(
            f"ffmpeg exited rc={proc.returncode}: {err_tail}"
        )

    if not stdout:
        raise OpusEncodeError("ffmpeg produced no output")

    return stdout
