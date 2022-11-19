from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class GoogleReverseGeocodingRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
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
