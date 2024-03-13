from typing import List

from domain.queries import EmailRulesByNamesQuery
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

    async def get_email_rules_by_names(
        self,
        names: List[str]
    ):
        query = EmailRulesByNamesQuery(
            rule_names=names)

        results = self.collection.find(
            query.get_query())

        entities = await results.to_list(
            length=None)

        return entities


class GoogleEmailHistoryRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Google',
            collection='History')
