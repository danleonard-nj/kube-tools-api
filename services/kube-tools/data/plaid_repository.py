from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
from framework.logger import get_logger


logger = get_logger(__name__)


class PlaidAdminItemRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='plaid_admin',
            collection='plaid_items')

    async def get_item_by_access_token(self, access_token: str):
        """Get item by access_token."""
        logger.info(f"Getting item for access_token: {access_token}")
        item_doc = await self.collection.find_one({'access_token': access_token})
        return item_doc


class PlaidAccountRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='plaid',
            collection='accounts')

    async def upsert_account(self, account: dict):
        """Upsert an account by account_id."""
        logger.info(f"Upserting account in repo: {account.get('account_id')}")
        result = await self.collection.replace_one(
            {'account_id': account['account_id']},
            account,
            upsert=True
        )
        logger.info(f"Upsert result: matched={result.matched_count}, modified={result.modified_count}, upserted_id={result.upserted_id}")
        return result

    async def get_all_accounts(self):
        """Get all accounts."""
        logger.info("Getting all accounts from repo")
        accounts = await self.collection.find().to_list(length=None)
        logger.info(f"Found {len(accounts)} accounts")
        return accounts


class PlaidTransactionRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='plaid',
            collection='transactions')

    async def update_transaction(self, transaction_id: str, update_fields: dict):
        """Update a transaction by transaction_id with the given fields."""
        logger.info(f"Updating transaction in repo: {transaction_id} with fields: {update_fields}")
        result = await self.collection.update_one(
            {'transaction_id': transaction_id},
            {'$set': update_fields}
        )
        logger.info(f"Update result: matched={result.matched_count}, modified={result.modified_count}")
        return result

    async def upsert_transaction(self, transaction: dict):
        """Upsert a transaction by transaction_id."""
        logger.info(f"Upserting transaction in repo: {transaction.get('transaction_id')}")
        result = await self.collection.replace_one(
            {'transaction_id': transaction['transaction_id']},
            transaction,
            upsert=True
        )
        logger.info(f"Upsert result: matched={result.matched_count}, modified={result.modified_count}, upserted_id={result.upserted_id}")
        return result

    async def delete_transaction(self, transaction_id: str):
        """Delete a transaction by transaction_id."""
        logger.info(f"Deleting transaction in repo: {transaction_id}")
        result = await self.collection.delete_one({'transaction_id': transaction_id})
        logger.info(f"Delete result: deleted_count={result.deleted_count}")
        return result

    async def find_transactions(self, query: dict, limit: Optional[int] = None):
        """Find transactions matching the query."""
        logger.info(f"Finding transactions with query: {query}, limit: {limit}")
        if limit:
            transactions = await self.collection.find(query).limit(limit).to_list(length=limit)
        else:
            transactions = await self.collection.find(query).to_list(length=None)
        logger.info(f"Found {len(transactions)} transactions")
        return transactions


class PlaidSyncRepository(MongoRepositoryAsync):
    def __init__(
        self,
        client: AsyncIOMotorClient
    ):
        super().__init__(
            client=client,
            database='plaid',
            collection='sync')

    async def get_sync_state(self, access_token: str):
        """Get sync state by access_token."""
        logger.info(f"Getting sync state for access_token: {access_token}")
        state_doc = await self.collection.find_one({'access_token': access_token})
        logger.info(f"Found sync state: {state_doc}")
        return state_doc

    async def upsert_sync_state(self, sync_state: dict):
        """Upsert sync state by access_token."""
        logger.info(f"Upserting sync state for access_token: {sync_state.get('access_token')}")
        result = await self.collection.replace_one(
            {'access_token': sync_state['access_token']},
            sync_state,
            upsert=True
        )
        logger.info(f"Upsert result: matched={result.matched_count}, modified={result.modified_count}, upserted_id={result.upserted_id}")
        return result
