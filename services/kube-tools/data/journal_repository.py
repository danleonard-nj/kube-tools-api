from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class JournalEntryRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Journal',
            collection='Entry')

    async def get_entries(
        self,
        start_timestamp: int,
        end_timestamp: int,
    ):
        query = {
            'timestamp': {
                '$gte': start_timestamp,
                '$lte': end_timestamp
            }
        }

        return await self.collection.find(query).to_list(
            length=None)


class JournalCategoryRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Journal',
            collection='Category')


class JournalUnitRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Journal',
            collection='Unit')
