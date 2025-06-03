from domain.queries import (GetApiEventsByLogIdsQuery, GetApiEventsQuery,
                            GetErrorApiEventsQuery)
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class InboundSMSRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Twilio',
            collection='InboundSMS')

    async def get_messages(
        self,
        limit: int = 10,
    ):
        if limit > 25:
            raise ValueError("Limit cannot exceed 25")

        return await (
            self.collection
            .find()
            .sort([('created_date', -1)])
            .limit(limit)
            .to_list(length=None)
        )
