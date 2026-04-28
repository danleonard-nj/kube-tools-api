"""Mongo persistence for full transcription runs (one row per transcription).

Schema (per spec)::

    {
      _id, created_at, pipeline_version, user_id, filename,
      upload_id,
      audio_stats: {duration_ms, sample_rate, channels,
                    loudness_p10/p50/p90_db, estimated_snr_db},
      vad_probability_stream: list[float],          # ~30 ms resolution
      chunk_plan: [
        {chunk_index, start_ms, end_ms, boundary_type,
         chosen_boundary, rejected_candidates: [...]}
      ],
      transcript: {merged_text, per_chunk: [...]},
      audio_status: "ephemeral" | "retained" | "upload_expired",
      audio_storage_ref: str | null,               # GridFS ObjectId
      feedback: {rating, reason, notes, submitted_at} | null,
    }
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

from framework.logger import get_logger
from framework.mongo.mongo_repository import MongoRepositoryAsync

logger = get_logger(__name__)


_DATABASE = "Transcriptions"
_COLLECTION = "TranscriptionRuns"
_GRIDFS_BUCKET = "TranscriptionAudio"


class TranscriptionRunRepository(MongoRepositoryAsync):
    """One row per transcription run.  Written on completion."""

    def __init__(self, client: AsyncIOMotorClient):
        super().__init__(client=client, database=_DATABASE, collection=_COLLECTION)
        self._client = client
        self._gridfs = AsyncIOMotorGridFSBucket(
            client[_DATABASE], bucket_name=_GRIDFS_BUCKET,
        )

    # ------------------------------------------------------------------
    # Run insert / lookup
    # ------------------------------------------------------------------

    async def insert_run(self, document: Dict[str, Any]) -> str:
        document.setdefault("created_at", datetime.utcnow())
        document.setdefault("audio_status", "ephemeral")
        document.setdefault("audio_storage_ref", None)
        document.setdefault("feedback", None)
        result = await self.collection.insert_one(document)
        return str(result.inserted_id)

    async def get_run(self, transcription_id: str) -> Optional[Dict[str, Any]]:
        doc = await self.collection.find_one({"_id": ObjectId(transcription_id)})
        if doc is not None:
            doc["_id"] = str(doc["_id"])
        return doc

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    async def set_feedback(
        self,
        transcription_id: str,
        feedback: Dict[str, Any],
        audio_status: str,
        audio_storage_ref: Optional[str],
    ) -> bool:
        update = {
            "feedback": feedback,
            "audio_status": audio_status,
            "audio_storage_ref": audio_storage_ref,
        }
        result = await self.collection.update_one(
            {"_id": ObjectId(transcription_id)},
            {"$set": update},
        )
        return result.matched_count > 0

    async def list_with_feedback(
        self,
        pipeline_version: Optional[str] = None,
        reason: Optional[str] = None,
        after: Optional[datetime] = None,
        before: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0,
        verbose: bool = False,
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {"feedback": {"$ne": None}}
        if pipeline_version:
            query["pipeline_version"] = pipeline_version
        if reason:
            query["feedback.reason"] = reason
        if after or before:
            created: Dict[str, Any] = {}
            if after:
                created["$gte"] = after
            if before:
                created["$lte"] = before
            query["created_at"] = created

        projection: Optional[Dict[str, int]] = None
        if not verbose:
            projection = {
                "vad_probability_stream": 0,
                "transcript.per_chunk": 0,
            }

        cursor = (
            self.collection.find(query, projection)
            .sort("created_at", -1)
            .skip(offset)
            .limit(limit)
        )
        results: List[Dict[str, Any]] = []
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    # ------------------------------------------------------------------
    # GridFS audio retention
    # ------------------------------------------------------------------

    async def store_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        transcription_id: str,
    ) -> str:
        oid = await self._gridfs.upload_from_stream(
            filename=filename,
            source=audio_bytes,
            metadata={"transcription_id": transcription_id},
        )
        return str(oid)

    async def fetch_audio(self, audio_storage_ref: str) -> Optional[bytes]:
        try:
            stream = await self._gridfs.open_download_stream(ObjectId(audio_storage_ref))
            return await stream.read()
        except Exception as exc:
            logger.warning("gridfs.fetch_audio failed ref=%s: %s", audio_storage_ref, exc)
            return None
