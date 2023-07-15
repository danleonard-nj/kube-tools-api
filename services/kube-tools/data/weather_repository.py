from flask.scaffold import F
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class WeatherRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Weather',
            collection='History')

    async def get_last_record_by_zipcode(
        self,
        zip_code: str
    ):
        query_filter = {
            'location_zipcode': zip_code
        }

        return self.collection.find_one(
            filter=query_filter,
            sort=[('timestamp', -1)])
