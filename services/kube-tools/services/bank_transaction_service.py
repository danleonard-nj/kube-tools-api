import uuid
from datetime import datetime, timedelta
from typing import List

from clients.plaid_client import PlaidClient
from data.bank_repository import BankTransactionsRepository
from domain.bank import (TRANSACTION_DEFAULT_LOOKBACK_DAYS, PlaidAccount,
                         PlaidTransaction, SyncActionType, SyncResult,
                         format_datetime)
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


class BankTransactionService:
    def __init__(
        self,
        configuration: Configuration,
        transaction_repository: BankTransactionsRepository,
        plaid_client: PlaidClient
    ):
        self._transaction_repository = transaction_repository
        self._plaid_client = plaid_client

        self._plaid_accounts = configuration.banking.get(
            'plaid_accounts', list())

    async def get_transactions(
        self,
        start_timestamp: int,
        end_timestamp: int = None,
        bank_keys: List[str] = None,
    ):
        ArgumentNullException.if_none(start_timestamp, 'start_timestamp')

        end_timestamp = (
            end_timestamp or DateTimeUtil.timestamp()
        )

        entities = await self._transaction_repository.get_transactions(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            bank_keys=bank_keys)

        logger.info(f'Fetched {len(entities)} transactions')

        transactions = [PlaidTransaction.from_entity(data=entity)
                        for entity in entities]

        return transactions

    async def sync_account_transactions(
        self,
        plaid_account: PlaidAccount,
        days_back: int = None,
        include_transactions: bool = False
    ) -> dict:

        # Sync the account transactions
        transactions = await self._sync_account_transactions(
            account=plaid_account,
            days_back=days_back)

        inserts = [x for x in transactions if x.action ==
                   SyncActionType.Insert]
        updates = [x for x in transactions if x.action ==
                   SyncActionType.Update]

        result = {
            'updates': len(updates),
            'inserts': len(inserts),
        }

        # Optionally include the entire transaction
        if include_transactions:
            result['transactions'] = transactions

        return result

    async def sync_transactions(
        self,
        days_back: int = None,
        include_transactions: bool = False
    ):
        sync_results = dict()
        for account in self._plaid_accounts:
            # Parse the account info from config
            plaid_account = PlaidAccount.from_configuration(account)

            logger.info(
                f'Parsed Plaid account: {plaid_account.bank_key}-{plaid_account.account_id}')

            sync_results[plaid_account.bank_key] = await self.sync_account_transactions(
                plaid_account,
                days_back=days_back,
                include_transactions=include_transactions)

        return sync_results

    async def _get_transaction_lookup(
        self,
        transactions: List[PlaidTransaction],
        account: PlaidAccount
    ):
        ArgumentNullException.if_none(transactions, 'transactions')
        ArgumentNullException.if_none(account, 'account')

        transaction_bks = [x.transaction_bk for x in transactions]

        # Fetch existing transactions that have already been synced
        existing_transaction_entities = await self._transaction_repository.get_transactions_by_transaction_bks(
            bank_key=account.bank_key,
            transaction_bks=transaction_bks)

        existing_transactions = [PlaidTransaction.from_entity(data=entity)
                                 for entity in existing_transaction_entities]

        return {
            x.transaction_bk: x for x in existing_transactions
        }

    async def _sync_account_transactions(
        self,
        account: PlaidAccount,
        days_back: int = None
    ):
        ArgumentNullException.if_none(account, 'account')

        logger.info(f'Syncing transactions for account: {account.bank_key}')

        account_ids = [account.account_id]
        end_date = datetime.now()

        # Get the start date
        start_date = (
            end_date -
            timedelta(days=days_back or TRANSACTION_DEFAULT_LOOKBACK_DAYS)
        )

        logger.info(f'Date range: {start_date} - {end_date}')

        # Fetch the transactions from Plaid
        response = await self._plaid_client.get_transactions(
            access_token=account.access_token,
            start_date=format_datetime(start_date),
            end_date=format_datetime(end_date),
            account_ids=account_ids)

        results = response.get('transactions', list())

        # Parse transaction domain models
        transactions = [
            PlaidTransaction.from_plaid_transaction_item(
                data=item,
                bank_key=account.bank_key)
            for item in results
        ]

        transaction_lookup = await self._get_transaction_lookup(
            transactions=transactions,
            account=account)

        sync_results = []
        sync_result = None

        for transaction in transactions:
            existing_transaction = transaction_lookup.get(
                transaction.transaction_bk)

            sync_result = await self._sync_transaction(
                existing_transaction=existing_transaction,
                transaction=transaction)

            sync_results.append(sync_result)

        return sync_results

    async def _sync_transaction(
        self,
        existing_transaction: PlaidTransaction,
        transaction: PlaidTransaction
    ):
        # Insert the transaction if it does not exist
        if existing_transaction is None:
            logger.info(f'Insert: {transaction.transaction_bk}')

            transaction.transaction_id = str(uuid.uuid4())
            transaction.last_operation = SyncActionType.Insert

            await self._transaction_repository.insert(
                document=transaction.to_dict())

            return SyncResult(
                transaction=transaction,
                action=SyncActionType.Insert)

        # Transactio hash key mismatch indicates an update
        if existing_transaction.hash_key != transaction.hash_key:
            logger.info(f'Updating: {transaction.transaction_bk}')

            # Update the timestamp to the last modified date
            transaction.timestamp = DateTimeUtil.timestamp()
            transaction.last_operation = SyncActionType.Update

            await self._transaction_repository.replace(
                selector=transaction.get_selector(),
                document=transaction.to_dict())

            return SyncResult(
                transaction=transaction,
                action=SyncActionType.Update,
                original_transaction=existing_transaction)

        transaction.last_operation = SyncActionType.NoAction
        replace_result = await self._transaction_repository.replace(
            selector=transaction.get_selector(),
            document=transaction.to_dict())

        return SyncResult(
            transaction=transaction,
            action=SyncActionType.NoAction)
