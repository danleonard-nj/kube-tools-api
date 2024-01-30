from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class ApiEventRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Invoker',
            collection='ApiEvent')
        
    async def get_events(
        self,
        start_timestamp: int,
        end_timestamp: int
    ):
        return await self.collection.find({
            'timestamp': {
                '$gte': start_timestamp,
                '$lte': end_timestamp
            }
        }).to_list(length=None)
        
    async def get_events_by_log_ids(
        self,
        cutoff_timestamp: int,
        log_ids: list[str]
    ):
        return await self.collection.find({
            'timestamp': {
                '$gte': cutoff_timestamp
            },
            'log_id': {
                '$nin': log_ids
            }
        }).to_list(length=None)
        
    async def get_error_events(
        self
    ):
        return await self.collection.find({
            'status_code': {
                '$ne': 200
            }
        }).to_list(length=None)
        
        


class ApiEventAlertRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Invoker',
            collection='ApiEventAlert')
