from typing import Dict, List

from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient


class MongoQuery:
    def get_query(
        self
    ) -> Dict:
        raise NotImplementedError()


class GetBalanceByBankKeyQuery(MongoQuery):
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


class GetBalanceHistoryQuery(MongoQuery):
    def __init__(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: List[str] = None
    ):
        self.start_timestamp = start_timestamp
        self.end_timestamp = end_timestamp
        self.bank_keys = bank_keys

    def get_query(
        self
    ):
        query_filter = {
            'timestamp': {
                '$gte': self.start_timestamp,
                '$lte': self.end_timestamp
            }
        }

        if (self.bank_keys is not None
                and any(self.bank_keys)):

            query_filter['bank_key'] = {
                '$in': self.bank_keys
            }

        return query_filter


class BankTransactionSyncLogRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='Bank',
            collection='TransactionSyncLog')


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

    async def get_balance_history(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: List[str] = None
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

    async def get_transactions_by_transaction_bks(
        self,
        bank_key: str,
        transaction_bks: str
    ):
        query_filter = {
            'bank_key': bank_key,
            'transaction_bk': {
                '$in': transaction_bks
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
