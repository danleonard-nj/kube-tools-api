from typing import List
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient
from framework.exceptions.nulls import ArgumentNullException
from domain.mongo import MongoCollection, MongoDatabase


class DeadManConfigurationRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Health,
            collection=MongoCollection.DeadManSwitchConfiguration)

    async def configuration_exists(
        self,
        configuration_id: str
    ):
        ArgumentNullException.if_none_or_whitespace(
            configuration_id, 'configuration_id')

        entity = await self.get({
            'configuration_id': configuration_id
        })

        return entity is not None

    async def get_configurations_by_ids(
        self,
        configuration_ids: List[str]
    ):

        ArgumentNullException.if_none(
            configuration_ids,
            'configuration_ids')

        entities = await self.get({
            'configuration_id': {
                '$in': configuration_ids
            }
        })

        return entities
