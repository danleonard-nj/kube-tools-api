import uuid

from clients.email_gateway_client import EmailGatewayClient
from clients.plaid_client import PlaidClient
from data.bank_repository import BankBalanceRepository
from domain.bank import (BALANCE_BANK_KEY_EXCLUSIONS_SHOW_ALL_ACCOUNTS,
                         BALANCE_BANK_KEY_EXCLUSIONS_SHOW_REDUCED_ACCOUNTS,
                         BALANCE_EMAIL_RECIPIENT, BALANCE_EMAIL_SUBJECT,
                         DEFAULT_AGE_CUTOFF_THRESHOLD_DAYS, BankBalance,
                         CoinbaseAccountConfiguration, GetBalancesResponse,
                         PlaidAccount, PlaidBalance)
from domain.enums import BankKey, SyncType
from domain.features import Feature
from framework.clients.cache_client import CacheClientAsync
from framework.clients.feature_client import FeatureClientAsync
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.utilities.iter_utils import first
from models.bank_config import BankingConfig
from services.coinbase_service import CoinbaseService
from services.event_service import EventService
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


class BalanceSyncServiceError(Exception):
    pass


class BalanceSyncService:
    def __init__(
        self,
        configuration: Configuration,
        balance_repository: BankBalanceRepository,
        email_client: EmailGatewayClient,
        event_service: EventService,
        plaid_client: PlaidClient,
        coinbase_service: CoinbaseService,
        feature_client: FeatureClientAsync,
        cache_client: CacheClientAsync,
        config: BankingConfig
    ):
        self._balance_repository = balance_repository
        self._email_client = email_client
        self._event_service = event_service
        self._feature_client = feature_client
        self._plaid_client = plaid_client
        self._coinbase_service = coinbase_service
        self._cache_client = cache_client

        self._plaid_accounts = config.plaid_accounts
        self._coinbase_accounts = config.coinbase_accounts
        self._age_cutoff_threshold_days = config.age_cutoff_threshold_days

    async def get_balance(
        self,
        bank_key: BankKey,
        sync_type: SyncType = None
    ) -> BankBalance:

        ArgumentNullException.if_none_or_whitespace(bank_key, 'bank_key')

        entity = await self._balance_repository.get_balance_by_bank_key_sync_type(
            bank_key=bank_key,
            sync_type=sync_type)

        if entity is None:
            logger.info(f'Could not find balance for bank {bank_key}')
            return

        balance = BankBalance.from_entity(
            data=entity)

        return balance

    async def get_balances(
        self
    ) -> list[BankBalance]:

        logger.info('Getting bank balances')

        is_all_accounts_enabled, show_crypto_balances, use_age_cutoff_threshold = await TaskCollection(
            self._feature_client.is_enabled(feature_key=Feature.BankBalanceDisplayAllAccounts),
            self._feature_client.is_enabled(feature_key=Feature.BankBalanceDisplayCryptoBalances),
            self._feature_client.is_enabled(feature_key=Feature.BankBalanceUseAgeCutoffThreshold)).run()

        logger.info(f'All accounts enabled: {is_all_accounts_enabled}')
        logger.info(f'Show crypto balances: {show_crypto_balances}')
        logger.info(f'Use age cutoff threshold: {use_age_cutoff_threshold}')

        exclusions = (
            BALANCE_BANK_KEY_EXCLUSIONS_SHOW_ALL_ACCOUNTS
            if is_all_accounts_enabled
            else BALANCE_BANK_KEY_EXCLUSIONS_SHOW_REDUCED_ACCOUNTS
        )

        logger.info(f'Exclusions: {exclusions}')

        keys = [key for key in BankKey
                if key.value not in exclusions]

        if show_crypto_balances:
            logger.info('Including crypto balances')
            keys.extend([BankKey.Bitcoin, BankKey.Solana])

        logger.info(f'Fetching {len(keys)} balances')

        results = await TaskCollection(*[
            self.get_balance(key)
            for key in keys]).run()

        # Filter out any balances that are older than the cutoff threshold from being displayed
        if use_age_cutoff_threshold:
            age_cutoff = DateTimeUtil.timestamp() - (60 * 60 * 24 * int(self._age_cutoff_threshold_days))
            logger.info(f'Using age cutoff threshold: {age_cutoff}')

            for result in results:
                if result.timestamp < age_cutoff:
                    logger.info(f'Removing key due to age threshold: {result.bank_key}')
                    results.remove(result)

        # Sort the results by the bank key as they'll come back in random order
        results = [x for x in results if x]
        results.sort(key=lambda x: x.bank_key, reverse=True)

        return GetBalancesResponse(
            balances=results)

    async def get_balance_history(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: list[str]
    ):
        ArgumentNullException.if_none_or_whitespace(bank_keys, 'bank_keys')
        ArgumentNullException.if_none(start_timestamp, 'start_timestamp')
        ArgumentNullException.if_none(end_timestamp, 'end_timestamp')

        logger.info(f'Getting balance history for bank {bank_keys}')

        # Validate provided bank keys
        for bank_key in bank_keys:
            if bank_key not in BankKey.values():
                raise BalanceSyncServiceError(
                    f"'{bank_key}' is not a valid bank key")

        entities = await self._balance_repository.get_balance_history(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            bank_keys=bank_keys)

        logger.info(f'Fetched {len(entities)} balance history records')

        balances = [BankBalance.from_entity(data=entity)
                    for entity in entities]

        return balances

    async def capture_account_balance(
        self,
        bank_key: str,
        balance: float,
        tokens: int = 0,
        message_bk: str = None,
        sync_type=SyncType.Email
    ):
        ArgumentNullException.if_none_or_whitespace(bank_key, 'bank_key')
        ArgumentNullException.if_none(balance, 'balance')

        logger.info(f'Capturing balance for bank {bank_key}')

        balance = BankBalance(
            balance_id=str(uuid.uuid4()),
            bank_key=bank_key,
            balance=round(balance, 2),
            gpt_tokens=tokens,
            message_bk=message_bk,
            sync_type=sync_type,
            timestamp=DateTimeUtil.timestamp())

        result = await self._balance_repository.insert(
            document=balance.to_dict())

        await self._handle_balance_capture_alert_email(
            balance=balance)

        logger.info(f'Inserted bank record for key: {bank_key}: {result.inserted_id}')

        return balance

    async def delete_balance(self, balance_id: str):
        """Delete a balance by balance_id."""
        ArgumentNullException.if_none_or_whitespace(balance_id, 'balance_id')

        logger.info(f'Deleting balance: {balance_id}')

        result = await self._balance_repository.delete_balance(balance_id=balance_id)

        if result.deleted_count == 0:
            logger.warning(f'Balance not found: {balance_id}')
            raise BalanceSyncServiceError(f'Balance not found: {balance_id}')

        logger.info(f'Deleted balance: {balance_id}')
        return {'deleted_count': result.deleted_count}

    async def run_sync(self) -> list:
        """
        Entry point for running a full sync of all balances.
        """
        return await self.sync_balances()

    async def sync_balances(self, run_async: bool = True) -> list:
        """
        Sync all Plaid and Coinbase accounts, either asynchronously or sequentially.
        Returns a list of updated balances.
        """
        logger.info(f'Starting sync_balances (run_async={run_async})')
        # Check which syncs are enabled
        sync_plaid_enabled, coinbase_enabled = await TaskCollection(
            self._feature_client.is_enabled(feature_key=Feature.PlaidSync),
            self._feature_client.is_enabled(feature_key=Feature.CoinbaseSync)
        ).run()

        results = []
        # Sync Plaid accounts if enabled
        if sync_plaid_enabled:
            plaid_results = await self._sync_accounts(
                accounts=self._plaid_accounts,
                sync_func=self.sync_plaid_account,
                run_async=run_async,
                label='Plaid'
            )
            results.extend(plaid_results)
        # Sync Coinbase accounts if enabled
        if coinbase_enabled:
            coinbase_results = await self.sync_coinbase_accounts()
            results.extend(coinbase_results)
        logger.info(f'Sync complete: {len(results)} accounts updated')
        return [x for x in results if x is not None]

    async def _sync_accounts(self, accounts: list[PlaidAccount], sync_func, run_async: bool, label: str) -> list:
        """
        Helper to sync a list of accounts using the provided sync function.
        Supports both async and sequential execution.
        """
        logger.info(f'Syncing {label} accounts (run_async={run_async})')
        if run_async:
            return await TaskCollection(*[sync_func(account) for account in accounts]).run()
        else:
            results = []
            for account in accounts:
                results.append(await sync_func(account))
            return results

    async def sync_plaid_account(
        self,
        account: dict
    ) -> PlaidBalance:
        logger.info(f'Syncing plaid account: {account}')

        # Parse the account configuration
        config = PlaidAccount.from_config_model(account)

        # Get the latest Plaid balance for the account
        latest_balance = await self.get_balance(
            bank_key=config.bank_key)
        # sync_type=SyncType.Plaid)

        if latest_balance:
            logger.info(f'Latest Plaid balance: {latest_balance.bank_key}: {latest_balance.timestamp}')

        delta = (
            DateTimeUtil.timestamp() - latest_balance.timestamp
            if latest_balance is not None else 0
        )

        logger.info(f'Delta: {delta} seconds')

        # Skip the sync if the threshold has not been exceeded
        if 0 < delta < config.sync_threshold_seconds:
            logger.info(f'Skipping sync for {config.bank_key} due to threshold')
            return latest_balance

        balance = await self._fetch_plaid_account_balance(
            account=config)

        logger.info(f'Captured balance from plaid: {config.bank_key}: {balance.available_balance}')

        # Store the captured balance
        result = await self.capture_account_balance(
            bank_key=config.bank_key,
            balance=balance.available_balance,
            sync_type=str(SyncType.Plaid))

        return result

    async def sync_coinbase_accounts(
        self
    ):
        logger.info(f'Fetching Coinbase account data')

        balances = []
        coinbase_accounts = await self._coinbase_service.get_accounts()

        sync_configs = [CoinbaseAccountConfiguration.from_config_model(config)
                        for config in self._coinbase_accounts]

        for config in sync_configs:
            logger.info(f'Syncing Coinbase account: {config.currency_code}')

            # Get the Coinbase account for the currency code
            account = first(
                coinbase_accounts,
                lambda x: x.currency == config.currency_code)

            # No Coinbase account matching the currency code provided in the configuration
            if account is None:
                logger.info(f'Could not find account for currency: {config.currency_code}')
                continue

            balance = await self.capture_account_balance(
                bank_key=config.bank_key,
                balance=float(account.usd_amount),
                sync_type=str(SyncType.Coinbase))

            balances.append(balance)

        return balances

    async def _fetch_plaid_account_balance(
        self,
        account: PlaidAccount
    ):
        ArgumentNullException.if_none(account, 'account')

        balance_response = await self._plaid_client.get_balance(
            access_token=account.access_token)

        target_account = first(
            balance_response.get('accounts', list()),
            lambda x: x.get('account_id') == account.account_id)

        if target_account is None:
            logger.info(f'Could not find target account: {account.bank_key}: {account.account_id}')
            return

        balance = PlaidBalance.from_plaid_response(
            data=target_account)

        logger.info(f'Fetched plaid balance: {balance.account_name}: {balance.available_balance}')

        return balance

    async def _handle_balance_capture_alert_email(
        self,
        balance: BankBalance
    ):
        ArgumentNullException.if_none(balance, 'balance')

        is_enabled = await self._feature_client.is_enabled(
            feature_key=Feature.BankingBalanceCaptureEmailNotify)

        if not is_enabled:
            logger.info(f'Balance capture emails are disabled')
            return

        logger.info(f'Sending email for bank {balance.bank_key}')

        # Send an alert email when a bank balance has been
        email_request, endpoint = self._email_client.get_json_email_request(
            recipient=BALANCE_EMAIL_RECIPIENT,
            subject=f'{BALANCE_EMAIL_SUBJECT} - {balance.bank_key}',
            json=balance.to_dict())

        logger.info(f'Email request: {endpoint}: {email_request.to_dict()}')

        # Drop the trigger message on the service bus queue
        await self._event_service.dispatch_email_event(
            endpoint=endpoint,
            message=email_request.to_dict())
