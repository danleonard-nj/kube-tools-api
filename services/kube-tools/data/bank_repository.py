from domain.queries import (GetBalanceByBankKeyQuery, GetBalanceHistoryQuery,
                            GetTransactionsByTransactionBksQuery,
                            GetTransactionsQuery)
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class BankBalanceRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Bank',
            collection='Balance')

    async def get_balance_by_bank_key_sync_type(
        self,
        bank_key: str,
        sync_type: str = None
    ) -> dict:

        query = GetBalanceByBankKeyQuery(
            bank_key=bank_key,
            sync_type=sync_type)

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
            .sort(query.get_sort())
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
