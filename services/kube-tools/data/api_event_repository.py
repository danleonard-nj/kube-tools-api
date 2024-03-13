from domain.queries import (GetApiEventsByLogIdsQuery, GetApiEventsQuery,
                            GetErrorApiEventsQuery)
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
        query = GetApiEventsQuery(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp)

        return await (
            self.collection
            .find(query.get_query())
            .to_list(length=None)
        )

    async def get_events_by_log_ids(
        self,
        cutoff_timestamp: int,
        log_ids: list[str]
    ):
        query = GetApiEventsByLogIdsQuery(
            cutoff_timestamp=cutoff_timestamp,
            log_ids=log_ids)

        return await (
            self.collection
            .find(query.get_query())
            .to_list(length=None)
        )

    async def get_error_events(
        self
    ):
        query = GetErrorApiEventsQuery()

        return await (
            self.collection
            .find(query.get_query())
            .to_list(length=None)
        )
