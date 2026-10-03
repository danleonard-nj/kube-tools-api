from framework.mongo.mongo_repository import MongoRepositoryAsync
from pymongo import AsyncMongoClient


class GoogleReverseGeocodingRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncMongoClient
    ):
        super().__init__(
            client=client,
            database='Google',
            collection='ReverseGeocoding')

    async def query(self, filter, top=None):
        result = self.collection.find(filter)
        return await result.to_list(length=top)

    async def get_by_key(self, key):
        return await self.query({
            'key': key
        }, top=1)
