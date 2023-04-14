from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase


class DeadManSwitchRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Health,
            collection=MongoCollection.DeadManSwitch)

    async def configuration_exists(
        self,
        configuration_id: str
    ):
        entity = await self.get({
            'configuration_id': configuration_id
        })

        return entity is not None
