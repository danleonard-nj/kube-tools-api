from http import client
from framework.mongo.mongo_repository import MongoRepositoryAsync
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from framework.clients.cache_client import CacheClientAsync
from framework.logger import get_logger

from models.bank_config import PlaidConfig
from services.banking.models import PlaidItemModel
from clients.plaid_client import PlaidClient


logger = get_logger(__name__)
logger.info("Initializing PlaidSyncService")

# These are known to require min_last_updated_datetime (e.g., Capital One)
INSTITUTIONS_REQUIRING_MIN_LAST_UPDATED = {"ins_128026"}


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
        logger.info(f"Found item: {item_doc}")
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


# Models that match Plaid's API response

# Plaid AccountBalance model
class AccountBalance(BaseModel):
    available: Optional[float] = None
    current: Optional[float] = None
    iso_currency_code: Optional[str] = None
    unofficial_currency_code: Optional[str] = None
    limit: Optional[float] = None
    last_updated_datetime: Optional[str] = None


class Account(BaseModel):
    account_id: str
    access_token: str
    name: str
    official_name: Optional[str] = None
    type: str
    subtype: Optional[str] = None
    balances: AccountBalance
    mask: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Transaction(BaseModel):
    transaction_id: str
    account_id: str
    access_token: str
    amount: float
    date: datetime
    name: str
    category: Optional[List[str]] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SyncState(BaseModel):
    access_token: str
    cursor: str = ""
    last_sync: Optional[datetime] = None


class PlaidSyncService:

    def __init__(
        self,
        plaid_config: PlaidConfig,
        item_repo: PlaidAdminItemRepository,
        account_repo: PlaidAccountRepository,
        transaction_repo: PlaidTransactionRepository,
        sync_repo: PlaidSyncRepository,
        plaid_client: PlaidClient
    ):
        self.plaid_client = plaid_client
        self.items_repo = item_repo
        self.accounts = account_repo
        self.transactions = transaction_repo
        self.sync_state = sync_repo

    async def sync_balances(self, access_token: str, min_last_updated_datetime: datetime = None):
        """Sync account balances for a given access token."""
        logger.info(f"Starting balance sync for access_token: {access_token}")

        # Get institution ID from item data
        item_doc = await self.items_repo.get_item_by_access_token(access_token)
        institution_id = item_doc.get('institution_id') if item_doc else None
        logger.info(f"Institution ID: {institution_id}")

        # Build options for institutions that need min_last_updated_datetime
        options = None
        if institution_id in INSTITUTIONS_REQUIRING_MIN_LAST_UPDATED:
            logger.info(f"Institution {institution_id} requires min_last_updated_datetime")
            options = {
                "min_last_updated_datetime": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
            }
        else:
            logger.info(f"Institution {institution_id} does not require min_last_updated_datetime")

        # Call our custom Plaid client
        response = await self.plaid_client.get_balance(
            access_token=access_token,
            institution_id=institution_id,
            options=options
        )

        # Process and store account data
        await self._process_account_data(response['accounts'], access_token)

    async def _process_account_data(self, accounts_data: list, access_token: str):
        """Process and store account balance data."""
        for account_data in accounts_data:
            logger.info(f"Processing account: {account_data['account_id']}")

            # account_data is already a dict from JSON response
            account_dict = account_data

            # Create account model
            account = Account(
                account_id=account_dict['account_id'],
                access_token=access_token,
                name=account_dict['name'],
                official_name=account_dict.get('official_name'),
                type=account_dict['type'],
                subtype=account_dict.get('subtype'),
                balances=AccountBalance.model_validate(account_dict['balances']),
                mask=account_dict.get('mask')
            )

            # Store in database
            await self.accounts.upsert_account(account.model_dump())
            logger.info(f"Updated account: {account.account_id}")

    async def sync_transactions(self, access_token: str):
        """Sync transactions for a given access token."""
        logger.info(f"Starting transaction sync for access_token: {access_token}")

        # Get current sync state
        cursor = await self._get_sync_cursor(access_token)

        # Fetch transaction data from Plaid
        response = await self._fetch_transaction_data(access_token, cursor)

        # Process transaction changes
        await self._process_transaction_changes(response, access_token)

        # Update sync state
        await self._update_sync_state(access_token, response['next_cursor'])

    async def _get_sync_cursor(self, access_token: str) -> str:
        """Get the current sync cursor for transactions."""
        state_doc = await self.sync_state.get_sync_state(access_token)
        cursor = state_doc['cursor'] if state_doc else ''
        logger.info(f"Using cursor: {cursor}")
        return cursor

    async def _fetch_transaction_data(self, access_token: str, cursor: str) -> dict:
        """Fetch transaction data from Plaid API."""
        # Get institution ID for potential min_last_updated_datetime requirement
        item_doc = await self.items_repo.get_item_by_access_token(access_token)
        institution_id = item_doc.get('institution_id') if item_doc else None

        # Build options for institutions that need min_last_updated_datetime
        options = {
            "cursor": cursor,
            "count": 50
        }

        if institution_id in INSTITUTIONS_REQUIRING_MIN_LAST_UPDATED:
            logger.info(f"Institution {institution_id} requires min_last_updated_datetime for transactions")
            options["min_last_updated_datetime"] = datetime.now(timezone.utc).isoformat()

        response = await self.plaid_client.sync_transactions(
            access_token=access_token,
            institution_id=institution_id,
            options=options
        )

        logger.info(f"Received {len(response['added'])} new, {len(response['modified'])} modified, and {len(response['removed'])} removed transactions")
        return response

    async def _process_transaction_changes(self, response: dict, access_token: str):
        """Process added, modified, and removed transactions."""
        # Process added transactions
        for txn_data in response['added']:
            await self._add_transaction(txn_data, access_token)

        # Process modified transactions
        for txn_data in response['modified']:
            await self._update_transaction(txn_data)

        # Process removed transactions
        for txn_id in response['removed']:
            await self._remove_transaction(txn_id)

    async def _add_transaction(self, txn_data, access_token: str):
        """Add a new transaction."""
        logger.info(f"Adding transaction: {txn_data['transaction_id']}")

        # txn_data is already a dict from JSON response
        txn_dict = txn_data
        transaction = Transaction(
            transaction_id=txn_dict['transaction_id'],
            account_id=txn_dict['account_id'],
            access_token=access_token,
            amount=txn_dict['amount'],
            date=txn_dict['date'],
            name=txn_dict['name'],
            category=txn_dict.get('category')
        )

        await self.transactions.upsert_transaction(transaction.model_dump())
        logger.info(f"Transaction added: {transaction.transaction_id}")

    async def _update_transaction(self, txn_data):
        """Update an existing transaction."""
        # txn_data is already a dict from JSON response
        txn_dict = txn_data
        logger.info(f"Updating transaction: {txn_dict['transaction_id']}")

        update_fields = {
            'amount': txn_dict['amount'],
            'name': txn_dict['name'],
            'updated_at': datetime.utcnow()
        }

        await self.transactions.update_transaction(txn_dict['transaction_id'], update_fields)
        logger.info(f"Transaction updated: {txn_dict['transaction_id']}")

    async def _remove_transaction(self, txn_id: str):
        """Remove a transaction."""
        logger.info(f"Removing transaction: {txn_id}")
        await self.transactions.delete_transaction(txn_id)
        logger.info(f"Transaction removed: {txn_id}")

    async def _update_sync_state(self, access_token: str, next_cursor: str):
        """Update the sync state with new cursor and timestamp."""
        sync_state = SyncState(
            access_token=access_token,
            cursor=next_cursor,
            last_sync=datetime.utcnow()
        )

        await self.sync_state.upsert_sync_state(sync_state.model_dump())
        logger.info(f"Sync state updated for access_token: {access_token}")

    async def sync_all(self):
        """Sync balances for all linked items."""
        logger.info("Starting sync for all items")

        # Get all linked items
        items = await self._get_all_items()
        logger.info(f"Found {len(items)} items to sync")

        # Sync each item
        for item in items:
            # if 'capital' not in item.institution_name.lower():
            #     logger.info(f"Skipping item {item.institution_name} due to filter")
            #     continue
            try:
                logger.info(f"Syncing item: {item.institution_name} (access_token: {item.access_token[:20]}...)")
                await self.sync_balances(item.access_token)
                logger.info(f"Successfully synced item: {item.institution_name}")
            except Exception as e:
                logger.error(f"Failed to sync item {item.institution_name}: {e}")
                # Continue with other items even if one fails

    async def _get_all_items(self) -> List[PlaidItemModel]:
        """Get all Plaid items from the database."""
        accounts = await self.items_repo.get_all()
        return [PlaidItemModel.model_validate(item) for item in accounts]

    async def get_account_balances(self):
        logger.info("Retrieving all account balances")
        accounts = await self.accounts.get_all_accounts()
        return [Account.model_validate(account) for account in accounts]

    async def get_transactions(
        self,
        account_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Transaction]:
        logger.info(f"Retrieving transactions for account_id: {account_id}, start_date={start_date}, end_date={end_date}")
        query = {'account_id': account_id}
        if start_date and end_date:
            query['date'] = {'$gte': start_date, '$lte': end_date}
        elif start_date:
            query['date'] = {'$gte': start_date}
        elif end_date:
            query['date'] = {'$lte': end_date}
        transactions = await self.transactions.find_transactions(query)
        return [Transaction.model_validate(txn) for txn in transactions]
