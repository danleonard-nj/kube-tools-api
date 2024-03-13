from domain.mongo import MongoCollection, MongoDatabase
from domain.queries import GetChatGptHistoryQuery
from framework.exceptions.nulls import ArgumentNullException
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class ChatGptRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database=MongoDatabase.ChatGPT,
            collection=MongoCollection.History)

    async def get_history(
        self,
        start_timestamp,
        end_timestamp,
        endpoint: str = None
    ):
        ArgumentNullException.if_none(start_timestamp, 'start_timestamp')
        ArgumentNullException.if_none(end_timestamp, 'end_timestamp')

        query = GetChatGptHistoryQuery(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            endpoint=endpoint)

        return await (self.collection
                      .find(query.get_query())
                      .to_list(length=None))
