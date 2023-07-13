import enum
from typing import Dict, List
import uuid
from framework.configuration import Configuration
from data.bank_repository import BankBalanceRepository
from framework.logger import get_logger

from utilities.utils import DateTimeUtil
from framework.serialization import Serializable

logger = get_logger(__name__)

BANK_KEY_WELLS_FARGO = 'wells-fargo'


class BankKey(enum.StrEnum):
    WellsFargo = 'wells-fargo'


class BankBalance(Serializable):
    def __init__(
        self,
        balance_id: str,
        bank_key: str,
        balance: float,
        timestamp: int
    ):
        self.balance_id = balance_id
        self.bank_key = bank_key
        self.balance = balance
        self.timestamp = timestamp

    @staticmethod
    def from_entity(
        data: Dict
    ):
        return BankBalance(
            balance_id=data.get('balance_id'),
            bank_key=data.get('bank_key'),
            balance=data.get('balance'),
            timestamp=data.get('timestamp'))


class BankService:
    def __init__(
        self,
        configuration: Configuration,
        balance_repository: BankBalanceRepository,
    ):
        self.__configuration = configuration
        self.__balance_repository = balance_repository

    async def capture_balance(
        self,
        bank_key: str,
        balance: float,
    ):
        logger.info(f'Capturing balance for bank {bank_key}')

        balance = BankBalance(
            balance_id=str(uuid.uuid4()),
            bank_key=bank_key,
            balance=balance,
            timestamp=DateTimeUtil.timestamp())

        result = await self.__balance_repository.insert(
            document=balance.to_dict())

        logger.info(f'Inserted bank record: {result.inserted_id}')

        return balance

    async def get_balance(
        self,
        bank_key: str
    ) -> BankBalance:

        logger.info(f'Getting balance for bank {bank_key}')

        # Parse the bank key, this will throw if an
        # invalid key is provided
        key = BankKey(bank_key)

        query_filter = {
            'bank_key': key.value
        }

        entity = await self.__balance_repository.collection.find_one(
            filter=query_filter,
            sort=[('timestamp', -1)])

        if entity is None:
            logger.info(f'Could not find balance for bank {bank_key}')
            raise Exception(
                f"Could not find balance for bank with key '{bank_key}'")

        logger.info(f'Found balance for bank {bank_key}: {entity}')

        balance = BankBalance.from_entity(
            data=entity)

        return balance

    async def get_balances(
        self
    ) -> List[BankBalance]:

        logger.info(f'Getting balances for all banks')

        results = list()
        for key in BankKey:
            logger.info(f'Getting balance for bank {key}')
            result = await self.get_balance(
                bank_key=str(key))

            results.append(result)

        return results
