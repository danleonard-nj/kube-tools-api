from domain.queries import GetWeatherByZipCodeCardinalityKeyQuery
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

    async def get_weather_by_zip_cardinality_key(
        self,
        zip_code: str,
        cardinality_key: str
    ):
        query = GetWeatherByZipCodeCardinalityKeyQuery(
            location_zipcode=zip_code,
            cardinality_key=cardinality_key)

        return await self.get(query.get_query())
