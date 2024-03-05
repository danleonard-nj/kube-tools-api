from domain.mongo import MongoQuery
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class GetEventsQuery(MongoQuery):
    def __init__(
        self,
        start_timestamp: int,
        end_timestamp: int
    ):
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp

    def get_query(
        self
    ):
        return {
            'timestamp': {
                '$gte': self.start_timestamp,
                '$lte': self.end_timestamp
            }
        }


class GetEventsByLogIdsQuery(MongoQuery):
    def __init__(
        self,
        cutoff_timestamp: int,
        log_ids: list[str]
    ):
        self.cutoff_timestamp = cutoff_timestamp
        self.log_ids = log_ids

    def get_query(
        self
    ):
        return {
            'timestamp': {
                '$gte': self.cutoff_timestamp
            },
            'log_id': {
                '$nin': self.log_ids
            }
        }


class GetErrorEventsQuery(MongoQuery):
    def __init__(
        self,
    ):
        pass

    def get_query(
        self
    ):
        return {
            'status_code': {
                '$ne': 200
            }
        }


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
        query = GetEventsQuery(
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
        query = GetEventsByLogIdsQuery(
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
        query = GetErrorEventsQuery()

        return await (
            self.collection
            .find(query.get_query())
            .to_list(length=None)
        )
