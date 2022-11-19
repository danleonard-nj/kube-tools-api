from domain.mongo import MongoCollection
from domain.podcasts import Podcasts
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class PodcastRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=Podcasts.Database,
            collection=Podcasts.Collection)

        self.database = self.client.get_database(
            Podcasts.Database)
        self.collection = self.database.get_collection(
            Podcasts.Collection)
