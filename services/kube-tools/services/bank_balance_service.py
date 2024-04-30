import uuid
from clients.email_gateway_client import EmailGatewayClient
from clients.plaid_client import PlaidClient
from data.bank_repository import BankBalanceRepository
from domain.bank import (BALANCE_BANK_KEY_EXCLUSIONS, BALANCE_EMAIL_RECIPIENT,
                         BALANCE_EMAIL_SUBJECT, BankBalance,
                         GetBalancesResponse, PlaidAccount, PlaidBalance)
from domain.cache import CacheKey
from domain.enums import BankKey, SyncType
from domain.features import Feature
from framework.clients.feature_client import FeatureClientAsync
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.utilities.iter_utils import first
from services.event_service import EventService
from utilities.utils import DateTimeUtil, fire_task
from framework.clients.cache_client import CacheClientAsync

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
        feature_client: FeatureClientAsync,
        cache_client: CacheClientAsync
    ):
        self._balance_repository = balance_repository
        self._email_client = email_client
        self._event_service = event_service
        self._feature_client = feature_client
        self._plaid_client = plaid_client
        self._cache_client = cache_client

        self._plaid_accounts = configuration.banking.get(
            'plaid_accounts', list())

    async def run_sync(
        self
    ):
        return await self.sync_balances()

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
            balance=balance,
            gpt_tokens=tokens,
            message_bk=message_bk,
            sync_type=sync_type,
            timestamp=DateTimeUtil.timestamp())

        result = await self._balance_repository.insert(
            document=balance.to_dict())

        await self._handle_balance_capture_alert_email(
            balance=balance)

        logger.info(f'Inserted bank record: {result.inserted_id}')

        return balance

    async def sync_balances(
        self,
        run_async: bool = True
    ):
        logger.info(f'Running async: {run_async}')

        results = []
        if run_async:
            # Sync all plaid accounts asynchronously
            results = await TaskCollection(*[
                self.sync_plaid_account(account)
                for account in self._plaid_accounts]).run()
        else:
            for account in self._plaid_accounts:
                results.append(await self.sync_plaid_account(account))

        return results

    async def sync_plaid_account(
        self,
        account: dict
    ) -> PlaidBalance:
        logger.info(f'Syncing plaid account: {account}')

        # Parse the account configuration
        config = PlaidAccount.from_configuration(account)

        # Get the latest balance for the account
        latest_balance = await self.get_balance(
            bank_key=config.bank_key)

        logger.info(f'Latest balance: {latest_balance.bank_key}: {latest_balance.timestamp}')

        delta = (
            DateTimeUtil.timestamp() - latest_balance.timestamp
            if latest_balance is not None else 0
        )

        logger.info(f'Delta: {delta} seconds')

        # Skip the sync if the threshold has not been exceeded
        if delta < config.sync_threshold_seconds:
            logger.info(f'Skipping sync for {config.bank_key} due to threshold')
            return latest_balance

        balance = await self._fetch_plaid_account_balance(
            account=config)

        logger.info(f'Captured balance from plaid: {config.bank_key}: {balance.available_balance}')

        # Store the captured balance
        await self.capture_account_balance(
            bank_key=config.bank_key,
            balance=balance.available_balance,
            sync_type=str(SyncType.Plaid))

        return balance

    async def _fetch_plaid_account_balance(
        self,
        account: PlaidAccount
    ):
        ArgumentNullException.if_none(account, 'account')

        key = CacheKey.plaid_account_balance(
            account_id=account.account_id,
            bank_key=account.bank_key)

        logger.info(f'Balance cache key: {key}')

        # Try to fetch the balance from cache
        balance = await self._cache_client.get_json(
            key=key)

        if balance is not None:
            logger.info(f'Cache hit for plaid account balance: {account.bank_key}')
            return PlaidBalance.from_entity(
                data=balance)

        logger.info(f'Cache miss for plaid account balance: {account.bank_key}')
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

        # Cache the balance response for 3 hours (another guard against
        # accidentally sending a bunch of very expensive requests to Plaid)
        fire_task(self._cache_client.set_json(
            key=key,
            value=balance.to_dict(),
            ttl=15
        ))

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

    async def get_balance(
        self,
        bank_key: BankKey
    ) -> BankBalance:

        ArgumentNullException.if_none_or_whitespace(bank_key, 'bank_key')

        entity = await self._balance_repository.get_balance_by_bank_key(
            bank_key=bank_key)

        if entity is None:
            logger.info(f'Could not find balance for bank {bank_key}')
            return

        balance = BankBalance.from_entity(
            data=entity)

        return balance

    async def get_balances(
        self
    ) -> list[BankBalance]:

        keys = [key for key in BankKey
                if key.value not in BALANCE_BANK_KEY_EXCLUSIONS]

        logger.info(f'Fetching balances for banks: {keys}')

        results = await TaskCollection(*[
            self.get_balance(key)
            for key in keys]).run()

        # Sort the results by the bank key as they'll come back in random order
        results = [x for x in results if x]
        results.sort(key=lambda x: x.bank_key)

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
