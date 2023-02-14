from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase


class SmsRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Sms,
            collection=MongoCollection.SmsConversations)

    async def query(self, filter):
        results = self.collection.find(filter)
        return await results.to_list(
            length=None)
