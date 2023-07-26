import uuid
from typing import List

from framework.clients.cache_client import CacheClientAsync
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger

from clients.email_gateway_client import EmailGatewayClient
from clients.plaid_client import PlaidClient
from data.bank_repository import BankBalanceRepository
from domain.bank import BankBalance, BankKey, PlaidBalance, SyncType
from services.event_service import EventService
from utilities.utils import DateTimeUtil
from framework.utilities.iter_utils import first

logger = get_logger(__name__)

BANK_KEY_WELLS_FARGO = 'wells-fargo'
EMAIL_RECIPIENT = 'dcl525@gmail.com'
EMAIL_SUBJECT = 'Bank Balance Captured'
BALANCE_CAPTURE_EMAILS_FEATURE_KEY = 'banking-balance-capture-emails'

BALANCE_BANK_KEY_EXCLUSIONS = [
    BankKey.CapitalOne,
    BankKey.Ally,
    BankKey.Synchrony
]


class PlaidAccount:
    def __init__(
        self,
        bank_key: str,
        access_token: str,
        account_id: str
    ):
        self.bank_key = bank_key
        self.access_token = access_token
        self.account_id = account_id

    @staticmethod
    def from_dict(data):
        return PlaidAccount(
            bank_key=data.get('bank_key'),
            access_token=data.get('access_token'),
            account_id=data.get('account_id'))


class BankService:
    def __init__(
        self,
        configuration: Configuration,
        balance_repository: BankBalanceRepository,
        email_client: EmailGatewayClient,
        event_service: EventService,
        cache_client: CacheClientAsync,
        feature_client: FeatureClientAsync,
        plaid_client: PlaidClient
    ):
        self.__configuration = configuration
        self.__balance_repository = balance_repository
        self.__email_client = email_client
        self.__event_service = event_service
        self.__cache_client = cache_client
        self.__feature_client = feature_client
        self.__plaid_client = plaid_client

        self.__plaid_accounts = configuration.banking.get(
            'plaid_accounts', list())

    async def run_sync(
        self
    ):
        return await self.sync_plaid_accounts()

    async def sync_plaid_accounts(
        self
    ):
        balances = list()

        for account in self.__plaid_accounts:
            logger.info(f'Syncing plaid account: {account}')

            # bank_key = account.get('bank_key')
            # access_token = account.get('access_token')
            # target_account_id = account.get('account_id')

            config = PlaidAccount.from_dict(account)

            # Fetch the balance from Plaid
            balance_response = await self.__plaid_client.get_balance(
                access_token=config.access_token)

            accounts = balance_response.get('accounts', list())
            logger.info(
                f'Accounts fetched for bank: {config.bank_key}: {len(accounts)}')

            target_account = first(
                accounts,
                lambda x: x.get('account_id') == config.account_id)

            if target_account is None:
                logger.info(
                    f'Could not find target account: {config.bank_key}: {config.account_id}')

                continue

            balance = PlaidBalance(
                data=target_account)

            balances.append(balance)

            logger.info(
                f'Captured balance from plaid: {balance.to_dict()}')

            # Store the captured balance
            await self.capture_balance(
                bank_key=config.bank_key,
                balance=balance.available_balance,
                sync_type=str(SyncType.Plaid))

        return balances

    async def capture_balance(
        self,
        bank_key: str,
        balance: float,
        tokens: int = 0,
        message_bk: str = None,
        sync_type=None
    ):
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

        result = await self.__balance_repository.insert(
            document=balance.to_dict())

        await self.__handle_balance_capture_alert_email(
            balance=balance)

        logger.info(f'Inserted bank record: {result.inserted_id}')

        return balance

    async def __handle_balance_capture_alert_email(
        self,
        balance: BankBalance
    ):
        is_enabled = await self.__feature_client.is_enabled(
            feature_key=BALANCE_CAPTURE_EMAILS_FEATURE_KEY)

        if not is_enabled:
            logger.info(f'Balance capture emails are disabled')
            return

        logger.info(f'Sending email for bank {balance.bank_key}')

        # Send an alert email when a bank balance has been
        email_request, endpoint = self.__email_client.get_json_email_request(
            recipient=EMAIL_RECIPIENT,
            subject=f'{EMAIL_SUBJECT} - {balance.bank_key}',
            json=balance.to_dict())

        logger.info(f'Email request: {endpoint}: {email_request.to_dict()}')

        # Drop the trigger message on the service bus queue
        await self.__event_service.dispatch_email_event(
            endpoint=endpoint,
            message=email_request.to_dict())

    async def get_balance(
        self,
        bank_key: str
    ) -> BankBalance:

        logger.info(f'Getting balance for bank {bank_key}')

        # Parse the bank key, this will throw if an
        # invalid key is provided
        key = BankKey(value=bank_key)

        entity = await self.__balance_repository.get_balance_by_bank_key(
            bank_key=str(key))

        if entity is None:
            logger.info(f'Could not find balance for bank {bank_key}')
            return

        logger.info(f'Found balance for bank {bank_key}: {entity}')

        balance = BankBalance.from_entity(
            data=entity)

        return balance

    async def get_balances(
        self
    ) -> List[BankBalance]:

        logger.info(f'Getting balances for all banks')

        results = list()
        missing = list()

        keys = [key.value for key in BankKey
                if key not in BALANCE_BANK_KEY_EXCLUSIONS]

        for key in keys:
            logger.info(f'Getting balance for bank {key}')
            result = await self.get_balance(
                bank_key=str(key))

            if result is None:
                missing.append(key)
            else:
                results.append(result)

        return {
            'balances': results,
            'no_data': missing
        }
