from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class WeatherStationRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='WeatherStation',
            collection='StationCoordinate')

    async def query(self, filter, top=None):
        result = self.collection.find(filter)
        return await result.to_list(length=top)


class ZipLatLongRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='WeatherStation',
            collection='ZipLatLong')

    async def query(self, filter, top=None):
        result = self.collection.find(filter)
        return await result.to_list(length=top)
