from typing import Dict, List

from domain.mongo import Queryable
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient

from domain.queries import GetBalanceByBankKeyQuery, GetBalanceHistoryQuery, GetTransactionsByTransactionBksQuery, GetTransactionsQuery


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
    ) -> dict:

        query = GetBalanceByBankKeyQuery(
            bank_key=bank_key)

        return await self.collection.find_one(
            filter=query.get_query(),
            sort=query.get_sort())

    async def get_balance_history(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: list[str] = None
    ):
        query = GetBalanceHistoryQuery(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            bank_keys=bank_keys
        )

        return await (
            self.collection
            .find(filter=query.get_query())
            .to_list(length=None)
        )


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
        bank_keys: list[str] = None
    ):
        query = GetTransactionsQuery(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            bank_keys=bank_keys
        )

        return await (
            self.collection
            .find(filter=query.get_query())
            .to_list(length=None)
        )

    async def get_transactions_by_transaction_bks(
        self,
        bank_key: str,
        transaction_bks: str
    ):
        query = GetTransactionsByTransactionBksQuery(
            bank_key=bank_key,
            transaction_bks=transaction_bks
        )

        return await (
            self.collection
            .find(filter=query.get_query())
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
