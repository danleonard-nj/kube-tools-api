import enum
from typing import Dict, List
import uuid
from framework.configuration import Configuration
from domain.bank import BankBalance, BankKey
from services.event_service import EventService
from clients.email_gateway_client import EmailGatewayClient
from data.bank_repository import BankBalanceRepository
from framework.logger import get_logger
from framework.clients.cache_client import CacheClientAsync
from utilities.utils import DateTimeUtil
from framework.serialization import Serializable
from framework.clients.feature_client import FeatureClientAsync

logger = get_logger(__name__)

BANK_KEY_WELLS_FARGO = 'wells-fargo'
EMAIL_RECIPIENT = 'dcl525@gmail.com'
EMAIL_SUBJECT = 'Bank Balance Captured'
BALANCE_CAPTURE_EMAILS_FEATURE_KEY = 'banking-balance-capture-emails'


class BankService:
    def __init__(
        self,
        configuration: Configuration,
        balance_repository: BankBalanceRepository,
        email_client: EmailGatewayClient,
        event_service: EventService,
        cache_client: CacheClientAsync,
        feature_client: FeatureClientAsync
    ):
        self.__configuration = configuration
        self.__balance_repository = balance_repository
        self.__email_client = email_client
        self.__event_service = event_service
        self.__cache_client = cache_client
        self.__feature_client = feature_client

    async def capture_balance(
        self,
        bank_key: str,
        balance: float,
        tokens: int = 0,
        message_bk: str = None
    ):
        logger.info(f'Capturing balance for bank {bank_key}')

        balance = BankBalance(
            balance_id=str(uuid.uuid4()),
            bank_key=bank_key,
            balance=balance,
            gpt_tokens=tokens,
            message_bk=message_bk,
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
        key = BankKey(
            value=bank_key)

        query_filter = {
            'bank_key': key.value
        }

        entity = await self.__balance_repository.collection.find_one(
            filter=query_filter,
            sort=[('timestamp', -1)])

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

        for key in BankKey:
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
