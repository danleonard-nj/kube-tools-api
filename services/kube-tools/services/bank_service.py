import uuid
from typing import Dict, List

from framework.logger import get_logger
import pandas as pd

from data.bank_repository import BankWebhooksRepository
from domain.bank import BankBalance, PlaidWebhookData
from services.bank_balance_service import BalanceSyncService
from services.bank_transaction_service import BankTransactionService
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


def format_datetime(dt):
    logger.info(f'Formatting datetime: {dt}')
    return dt.strftime('%Y-%m-%d')


class BankService:
    def __init__(
        self,
        webhook_repository: BankWebhooksRepository,
        transaction_service: BankTransactionService,
        balance_service: BalanceSyncService
    ):
        self.__webhooks_repository = webhook_repository
        self.__transaction_service = transaction_service
        self.__balance_service = balance_service

    async def run_balance_sync(
        self
    ):
        return await self.__balance_service.sync_balances()

    async def run_transaction_sync(
        self,
        days_back: int = None,
        include_transactions: bool = False
    ):
        return await self.__transaction_service.sync_transactions(
            days_back=days_back,
            include_transactions=include_transactions)

    async def handle_webhook(
        self,
        data: Dict
    ):
        logger.info(
            f'Handling inbound Plaid webhook: {DateTimeUtil.get_iso_date()}')

        webhook_record = PlaidWebhookData(
            request_id=str(uuid.uuid4()),
            data=data,
            timestamp=DateTimeUtil.timestamp())

        logger.info(f'Webhook record: {webhook_record.to_dict()}')

        await self.__webhooks_repository.insert(
            document=webhook_record.to_dict())

        return dict()

    async def get_balance_history(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: List[str],
        group_institutions: bool = False
    ) -> List[BankBalance]:

        records = await self.__balance_service.get_balance_history(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            bank_keys=bank_keys)

        if not group_institutions:
            return records

        results = dict()
        for balance in records:
            if balance.bank_key not in results:
                results[balance.bank_key] = list()
            results[balance.bank_key].append(balance)
        return results

    async def get_balances(
        self
    ) -> List[BankBalance]:

        return await self.__balance_service.get_balances()

    async def get_balance(
        self,
        bank_key: str
    ) -> BankBalance:

        return await self.__balance_service.get_balance(
            bank_key=bank_key)

    async def get_transactions(
        self,
        start_timestamp: int,
        end_timestamp: int,
        bank_keys: List[str],
        group_institutions: bool = False
    ) -> Dict:

        records = await self.__transaction_service.get_transactions(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            bank_keys=bank_keys)

        if not group_institutions:
            return records

        results = dict()
        for record in records:
            if record.bank_key not in results:
                results[record.bank_key] = list()
            results[record.bank_key].append(record)
        return results

    async def capture_balance(
        self,
        bank_key: str,
        balance: float,
        tokens: int = 0,
        message_bk: str = None,
        sync_type=None
    ) -> BankBalance:

        return await self.__balance_service.capture_account_balance(
            bank_key=bank_key,
            balance=balance,
            tokens=tokens,
            message_bk=message_bk,
            sync_type=sync_type)
