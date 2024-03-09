import uuid
from typing import List

from clients.email_gateway_client import EmailGatewayClient
from clients.plaid_client import PlaidClient
from data.bank_repository import BankBalanceRepository
from domain.bank import (BALANCE_BANK_KEY_EXCLUSIONS, BALANCE_EMAIL_RECIPIENT,
                         BALANCE_EMAIL_SUBJECT, BankBalance, GetBalancesResponse, PlaidAccount,
                         PlaidBalance)
from domain.enums import BankKey, SyncType
from domain.exceptions import InvalidBankKeyException
from domain.features import Feature
from framework.clients.feature_client import FeatureClientAsync
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.utilities.iter_utils import first
from services.event_service import EventService
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


class BalanceSyncService:
    def __init__(
        self,
        configuration: Configuration,
        balance_repository: BankBalanceRepository,
        email_client: EmailGatewayClient,
        event_service: EventService,
        plaid_client: PlaidClient,
        feature_client: FeatureClientAsync
    ):
        self._balance_repository = balance_repository
        self._email_client = email_client
        self._event_service = event_service
        self._feature_client = feature_client
        self._plaid_client = plaid_client

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
        sync_type=None
    ):
        ArgumentNullException.if_none_or_whitespace(bank_key, 'bank_key')
        ArgumentNullException.if_none(balance, 'balance')

        logger.info(f'Capturing balance for bank {bank_key}')

        if sync_type is None:
            sync_type = str(SyncType.Email)

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
        self
    ):
        balances = list()

        async def handle_account(account: dict):
            balance = await self.sync_plaid_account(account)
            balances.append(balance)

        # Sync all plaid accounts asynchronously
        tasks = TaskCollection(*[handle_account(account)
                                 for account in self._plaid_accounts])

        await tasks.run()

        return balances

    async def sync_plaid_account(
        self,
        account: dict
    ) -> PlaidBalance:
        logger.info(f'Syncing plaid account: {account}')

        # Parse the account configuration
        config = PlaidAccount.from_configuration(account)

        # Fetch the balance from Plaid
        balance_response = await self._plaid_client.get_balance(
            access_token=config.access_token)

        accounts = balance_response.get('accounts', list())

        target_account = first(
            accounts,
            lambda x: x.get('account_id') == config.account_id)

        if target_account is None:
            logger.info(
                f'Could not find target account: {config.bank_key}: {config.account_id}')

            return

        # Parse the balance from the response
        balance = PlaidBalance.from_plaid_response(
            data=target_account)

        logger.info(
            f'Captured balance from plaid: {balance.to_dict()}')

        # Store the captured balance
        await self.capture_account_balance(
            bank_key=config.bank_key,
            balance=balance.available_balance,
            sync_type=str(SyncType.Plaid))

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
    ) -> List[BankBalance]:

        keys = [key for key in BankKey
                if key.value not in BALANCE_BANK_KEY_EXCLUSIONS]

        logger.info(f'Fetching balances for banks: {keys}')

        results = []

        async def handle_balance(key: BankKey):
            result = await self.get_balance(
                bank_key=key)

            if result is not None:
                results.append(result)

        tasks = TaskCollection(*[handle_balance(key)
                                 for key in keys])

        await tasks.run()

        results.sort(key=lambda x: x.bank_key)

        return GetBalancesResponse(
            balances=results)

    async def get_balance_history(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: List[str]
    ):
        ArgumentNullException.if_none_or_whitespace(bank_keys, 'bank_keys')
        ArgumentNullException.if_none(start_timestamp, 'start_timestamp')
        ArgumentNullException.if_none(end_timestamp, 'end_timestamp')

        logger.info(f'Getting balance history for bank {bank_keys}')

        # Validate provided bank keys
        for bank_key in bank_keys:
            if bank_key not in BankKey.values():
                raise InvalidBankKeyException(
                    f"'{bank_key}' is not a valid bank key")

        entities = await self._balance_repository.get_balance_history(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            bank_keys=bank_keys)

        logger.info(f'Fetched {len(entities)} balance history records')

        balances = [BankBalance.from_entity(data=entity)
                    for entity in entities]

        return balances
