from typing import Dict
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class ConversationRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Conversations',
            collection='Conversations')

    async def get_conversation_by_id(
        self,
        conversation_id: str
    ):
        query = {
            'conversation_id': conversation_id
        }

        return (
            await self.collection
            .find_one(filter=query)
        )

    async def get_conversation_by_recipient_status(
        self,
        recipient: str,
        status: str
    ):
        query = {
            'recipient': recipient,
            'status': status
        }

        return await self.collection.find_one(
            filter=query,
            sort=[('created_date', -1)])
