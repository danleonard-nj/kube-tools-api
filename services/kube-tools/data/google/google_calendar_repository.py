from framework.mongo.mongo_repository import MongoRepositoryAsync
from pymongo import AsyncMongoClient

from domain.mongo import MongoCollection, MongoDatabase


class GooleCalendarEventRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncMongoClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Google,
            collection='CalendarEvent')

    async def insert_many(
        self,
        documents: list[dict]
    ):
        return self.collection.insert_many(documents)
