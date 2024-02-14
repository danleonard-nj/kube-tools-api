from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase


class GooleCalendarEventRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
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
