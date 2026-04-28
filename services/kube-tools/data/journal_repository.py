from datetime import datetime
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from framework.logger import get_logger
from framework.mongo.mongo_repository import MongoRepositoryAsync

logger = get_logger(__name__)

_DATABASE = 'Journals'
_COLLECTION = 'JournalEntries'


class JournalRepository(MongoRepositoryAsync):
    def __init__(self, client: AsyncIOMotorClient):
        super().__init__(client=client, database=_DATABASE, collection=_COLLECTION)

    async def insert_entry(self, document: dict) -> str:
        document.setdefault('created_at', datetime.utcnow())
        document.setdefault('updated_at', datetime.utcnow())
        result = await self.collection.insert_one(document)
        return str(result.inserted_id)

    async def get_entry(self, entry_id: str) -> Optional[dict]:
        doc = await self.collection.find_one({'entry_id': entry_id})
        if doc is not None:
            doc['_id'] = str(doc['_id'])
        return doc

    async def list_recent(self, limit: int = 50) -> List[dict]:
        cursor = (
            self.collection
            .find({})
            .sort('created_at', -1)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            results.append(doc)
        return results

    async def update_entry(self, entry_id: str, update: dict) -> bool:
        update['updated_at'] = datetime.utcnow()
        result = await self.collection.update_one(
            {'entry_id': entry_id},
            {'$set': update},
        )
        return result.matched_count > 0

    async def delete_entry(self, entry_id: str) -> bool:
        result = await self.collection.delete_one({'entry_id': entry_id})
        return result.deleted_count > 0
