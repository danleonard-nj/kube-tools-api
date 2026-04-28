"""Redis-backed upload cache for raw audio bytes.

On audio upload we generate a UUID, write the *raw* bytes to Redis with a
30-minute TTL, and pass the UUID downstream as the ``upload_id``.  The
feedback endpoint resolves the UUID back to bytes when a user flags a bad
transcription, and copies the audio to GridFS for retention.

Key pattern: ``upload:{upload_id}``.  Value: raw bytes, no re-encoding.
"""

import uuid
from typing import Optional

from framework.clients.cache_client import CacheClientAsync
from framework.logger import get_logger

logger = get_logger(__name__)


KEY_PREFIX = "upload:"
DEFAULT_TTL_SECONDS = 30 * 60  # 30 minutes


def _key(upload_id: str) -> str:
    return f"{KEY_PREFIX}{upload_id}"


class UploadCache:
    """Thin wrapper around the existing async cache client."""

    def __init__(self, cache_client: CacheClientAsync):
        self._cache = cache_client

    async def put(self, audio_bytes: bytes, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
        """Store ``audio_bytes`` and return the generated ``upload_id``."""
        upload_id = uuid.uuid4().hex
        await self._cache.client.set(name=_key(upload_id), value=audio_bytes, ex=ttl_seconds)
        logger.info("upload_cache.put id=%s bytes=%d ttl=%ds", upload_id, len(audio_bytes), ttl_seconds)
        return upload_id

    async def get(self, upload_id: str) -> Optional[bytes]:
        """Return raw bytes or ``None`` if expired/missing."""
        raw = await self._cache.client.get(_key(upload_id))
        if raw is None:
            logger.info("upload_cache.miss id=%s", upload_id)
            return None
        return raw if isinstance(raw, bytes) else bytes(raw)

    async def delete(self, upload_id: str) -> None:
        await self._cache.client.delete(_key(upload_id))
