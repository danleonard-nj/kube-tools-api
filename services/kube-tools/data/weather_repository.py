from domain.mongo import Queryable
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class GetWeatherByZipCodeCardinalityKeyQuery(Queryable):
    def __init__(
        self,
        location_zipcode: str,
        cardinality_key: str
    ):
        self.location_zipcode = location_zipcode
        self.cardinality_key = cardinality_key

    def get_query(
        self
    ) -> dict:
        return {
            'location_zipcode': self.location_zipcode,
            'cardinality_key': self.cardinality_key
        }


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
