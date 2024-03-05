import unittest

from data.bank_repository import BankBalanceRepository
from domain.enums import SyncType
from framework.configuration import Configuration
from services.bank_service import BankService
from utilities.provider import ContainerProvider
from utilities.utils import DateTimeUtil


def configure_provider(provider):
    provider.resolve(Configuration).mongo = {
        'connection_string': 'mongodb://localhost:27017',
    }


def get_data(balance, sync_type):
    return {
        'bank_key': 'wells-fargo',
        'balance': balance,
        'gpt_tokens': 0,
        'message_bk': None,
        'sync_type': sync_type,
        'timestamp': DateTimeUtil.timestamp()
    }


class TestBankService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = ContainerProvider.get_service_provider()
        configure_provider(self.provider)

    async def test_get_balances(self):
        service = self.provider.resolve(BankService)

        repo: BankBalanceRepository = self.provider.resolve(
            BankBalanceRepository)

        balance = 100
        sync_type = str(SyncType.Email)

        item = get_data(balance, sync_type)

        await repo.collection.insert_one(document=item)

        result = await service.get_balances()

        result = result.balances[0]

        self.assertEqual(result.bank_key, 'wells-fargo')
        self.assertEqual(result.balance, balance)

    async def test_get_balance(self):
        service = self.provider.resolve(BankService)

        repo: BankBalanceRepository = self.provider.resolve(
            BankBalanceRepository)

        balance = 100
        sync_type = str(SyncType.Email)

        item = get_data(balance, sync_type)

        await repo.collection.insert_one(document=item)

        result = await service.get_balance('wells-fargo')

        self.assertIsNotNone(result)
        self.assertEqual(result.bank_key, 'wells-fargo')
        self.assertEqual(result.balance, balance)
