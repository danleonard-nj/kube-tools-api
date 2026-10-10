import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pymongo import AsyncMongoClient

from framework.logger import get_logger
from framework.mongo.mongo_repository import MongoRepositoryAsync

logger = get_logger(__name__)

_DATABASE = 'Journals'
_COLLECTION = 'JournalEntries'

_SEARCHABLE_FIELDS = (
    'title',
    'cleaned_transcript',
    'raw_transcript',
    'analysis.summary_short',
    'analysis.summary_detailed',
)


class JournalRepository(MongoRepositoryAsync):
    def __init__(self, client: AsyncMongoClient):
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

    async def list_recent(self, limit: int = 50, tags: Optional[List[str]] = None) -> List[dict]:
        query: Dict = {}
        if tags:
            query['tags'] = {'$all': tags}
        cursor = (
            self.collection
            .find(query)
            .sort('created_at', -1)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            results.append(doc)
        return results

    async def list_distinct_tags(self) -> List[str]:
        results = await self.collection.distinct('tags', {})
        return sorted(t for t in results if t)

    async def search_entries(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        text: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[dict], int]:
        """Entries newest first, and how many match in total.

        `start` is inclusive and `end` exclusive, both naive UTC like the
        stored `created_at`. `tags` must all be present. `text` matches
        case-insensitively, as a literal, anywhere in the title, transcripts or
        summaries. Segments and pre-polish text are never loaded.
        """
        query: Dict[str, Any] = {}
        if start or end:
            query['created_at'] = {
                **({'$gte': start} if start else {}),
                **({'$lt': end} if end else {}),
            }
        if tags:
            query['tags'] = {'$all': tags}
        if text:
            pattern = {'$regex': re.escape(text), '$options': 'i'}
            query['$or'] = [{field: pattern} for field in _SEARCHABLE_FIELDS]

        cursor = (
            self.collection
            .find(query, projection={'segments': False, 'pre_polish_transcript': False})
            .sort('created_at', -1)
            .skip(offset)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            results.append(doc)
        total = await self.collection.count_documents(query)
        return results, total

    async def count_tags(self) -> List[Dict[str, Any]]:
        """Every tag with the number of entries carrying it, most used first."""
        cursor = await self.collection.aggregate([
            {'$unwind': '$tags'},
            {'$match': {'tags': {'$nin': [None, '']}}},
            {'$group': {'_id': '$tags', 'entry_count': {'$sum': 1}}},
            {'$sort': {'entry_count': -1, '_id': 1}},
        ])
        return [
            {'tag': doc['_id'], 'entry_count': doc['entry_count']}
            async for doc in cursor
        ]

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

    async def list_entries_since(self, since: datetime, limit: int = 500) -> List[dict]:
        cursor = (
            self.collection
            .find({'created_at': {'$gte': since}})
            .sort('created_at', -1)
            .limit(limit)
        )
        results = []
        async for doc in cursor:
            doc['_id'] = str(doc['_id'])
            results.append(doc)
        return results
