"""Persistence for journal entry attachments.

Metadata is stored in the ``JournalAttachments`` collection; binary data
lives in the ``JournalFiles`` GridFS bucket — both inside the ``Journals``
database.
"""
import uuid
from datetime import datetime
from typing import List, Optional

from bson import ObjectId
from gridfs import AsyncGridFSBucket
from pymongo import AsyncMongoClient

from framework.logger import get_logger
from framework.mongo.mongo_repository import MongoRepositoryAsync

logger = get_logger(__name__)

_DATABASE = 'Journals'
_COLLECTION = 'JournalAttachments'
_GRIDFS_BUCKET = 'JournalFiles'


class JournalAttachmentRepository(MongoRepositoryAsync):
    def __init__(self, client: AsyncMongoClient):
        super().__init__(client=client, database=_DATABASE, collection=_COLLECTION)
        self._gridfs = AsyncGridFSBucket(
            client[_DATABASE], bucket_name=_GRIDFS_BUCKET,
        )

    async def store(
        self,
        entry_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> dict:
        attachment_id = str(uuid.uuid4())
        now = datetime.utcnow()

        oid = await self._gridfs.upload_from_stream(
            filename=filename,
            source=data,
            metadata={
                'entry_id': entry_id,
                'attachment_id': attachment_id,
                'content_type': content_type,
            },
        )

        doc = {
            'attachment_id': attachment_id,
            'entry_id': entry_id,
            'filename': filename,
            'content_type': content_type,
            'size_bytes': len(data),
            'created_at': now,
            'gridfs_id': str(oid),
        }
        await self.collection.insert_one(doc)
        return doc

    async def get_meta(self, attachment_id: str) -> Optional[dict]:
        doc = await self.collection.find_one({'attachment_id': attachment_id})
        if doc is not None:
            doc['_id'] = str(doc['_id'])
        return doc

    async def list_meta(self, entry_id: str) -> List[dict]:
        cursor = self.collection.find({'entry_id': entry_id}).sort('created_at', 1)
        results = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            results.append(doc)
        return results

    async def fetch_data(self, gridfs_id: str) -> Optional[bytes]:
        try:
            stream = await self._gridfs.open_download_stream(ObjectId(gridfs_id))
            return await stream.read()
        except Exception as exc:
            logger.warning('gridfs.fetch_data failed gridfs_id=%s: %s', gridfs_id, exc)
            return None

    async def delete(self, attachment_id: str) -> bool:
        doc = await self.collection.find_one({'attachment_id': attachment_id})
        if not doc:
            return False
        gridfs_id = doc.get('gridfs_id')
        if gridfs_id:
            try:
                await self._gridfs.delete(ObjectId(gridfs_id))
            except Exception as exc:
                logger.warning('gridfs.delete failed gridfs_id=%s: %s', gridfs_id, exc)
        result = await self.collection.delete_one({'attachment_id': attachment_id})
        return result.deleted_count > 0
