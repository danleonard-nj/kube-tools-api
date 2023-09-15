from flask.scaffold import F
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class VestingScheduleRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Vesting',
            collection='Schedule')

    async def get_schedule(
        self
    ):
        return await self.collection.find({}, {'_id': False}).to_list(
            length=None)
