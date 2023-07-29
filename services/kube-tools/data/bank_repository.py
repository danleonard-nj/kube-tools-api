from typing import Dict, List

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
            sort=[('timestamp', -1)])


class BankTransactionsRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Bank',
            collection='Transactions')

    async def get_transactions(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: List[str] = None
    ):
        query_filter = {
            'transaction_date': {
                '$gte': start_timestamp,
                '$lte': end_timestamp
            }
        }

        if bank_keys is not None:
            query_filter['bank_key'] = {
                '$in': bank_keys
            }

        return await (
            self.collection
            .find(filter=query_filter)
            .to_list(length=None)
        )

    async def get_transactions_by_transaction_ids(
        self,
        bank_key: str,
        transaction_ids: str
    ):
        query_filter = {
            'bank_key': bank_key,
            'transaction_id': {
                '$in': transaction_ids
            }
        }

        return await (
            self.collection
            .find(filter=query_filter)
            .to_list(length=None)
        )


class BankWebhooksRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Bank',
            collection='Webhooks')
