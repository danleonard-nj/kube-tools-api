from framework.mongo.mongo_repository import MongoRepositoryAsync
from pymongo import AsyncMongoClient


class GoogleLocationHistoryRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncMongoClient
    ):
        super().__init__(
            client=client,
            database='Google',
            collection='LocationHistory')

    async def query(self, filter, top=None):
        result = self.collection.find(filter)
        return await result.to_list(length=top)
