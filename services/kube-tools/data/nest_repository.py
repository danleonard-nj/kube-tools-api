from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class NestSensorRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Nest',
            collection='Sensor')

    async def get_by_device(
        self,
        device_id: str,
        start_timestamp: int
    ):
        result = self.collection.aggregate([
            {
                '$match': {
                    'sensor_id': device_id,
                    'timestamp': {
                        '$gte': int(start_timestamp)
                    }
                }
            }
        ])

        return await result.to_list(
            length=None)


class NestDeviceRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Nest',
            collection='Device')
