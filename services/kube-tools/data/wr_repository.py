from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase


class WellnessCheckRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.WellnessCheck,
            collection=MongoCollection.WellnessCheck)


class WellnessReplyRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.WellnessCheck,
            collection=MongoCollection.WellnessReply)
