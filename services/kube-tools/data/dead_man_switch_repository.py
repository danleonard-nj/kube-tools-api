from typing import Dict, List

from framework.exceptions.nulls import ArgumentNullException
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.mongo import MongoCollection, MongoDatabase


class DeadManSwitcHistoryhRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Health,
            collection=MongoCollection.DeadManSwitchHistory)


class DeadManSwitchRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.Health,
            collection=MongoCollection.DeadManSwitch)

    async def switch_exists_by_name(
        self,
        switch_name: str
    ) -> bool:

        ArgumentNullException.if_none_or_whitespace(switch_name, 'switch_name')

        entity = await self.get({
            'switch_name': switch_name
        })

        return entity is not None

    async def get_switches_by_configuration_id(
        self,
        configuration_id: str
    ) -> List[Dict]:

        ArgumentNullException.if_none_or_whitespace(
            configuration_id, 'configuration_id')

        entities = self.collection.find({
            'configuration_id': configuration_id
        })

        return await entities.to_list(
            length=None)

    async def get_active_switches(
        self
    ) -> List[Dict]:

        entities = self.collection.find({
            'is_active': True
        })

        return await entities.to_list(
            length=None)
