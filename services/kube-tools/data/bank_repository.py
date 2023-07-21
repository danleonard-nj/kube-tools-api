from typing import Dict

from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class GetBalanceByBankKeyQuery:
    def __init__(
        self,
        bank_key: str
    ):
        self.bank_key = bank_key

    def get_query(
        self
    ):
        return {
            'bank_key': self.bank_key
        }


class BankBalanceRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Bank',
            collection='Balance')

    async def get_balance_by_bank_key(
        self,
        bank_key: str
    ) -> Dict:

        query = GetBalanceByBankKeyQuery(
            bank_key=bank_key)

        return await self.collection.find_one(
            filter=query.get_query(),
            sort=[('timestamp', 1)])
