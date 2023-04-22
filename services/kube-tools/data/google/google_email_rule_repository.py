from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class GoogleEmailRuleRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Google',
            collection='EmailRule')

    async def email_rule_exists_by_id(
        self,
        rule_id: str
    ):
        rule = await self.collection.find_one({
            'rule_id': rule_id
        })

        return rule is not None


class GoogleEmailHistoryRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Google',
            collection='History')
