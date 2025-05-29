import unittest
from unittest.mock import AsyncMock, MagicMock
from domain.enums import BankKey, SyncType
from domain.google import GmailEmail, GmailEmailRule
from services.gmail_balance_sync_service import GmailBankSyncService
import datetime


class TestGmailBankSyncService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Mock dependencies
        self.mock_bank_service = AsyncMock()
        self.mock_chat_gpt_service = AsyncMock()
        self.mock_cache_client = AsyncMock()
        self.mock_config = MagicMock()
        self.mock_config.banking.get.return_value = []
        self.service = GmailBankSyncService(
            configuration=self.mock_config,
            bank_service=self.mock_bank_service,
            chat_gpt_service=self.mock_chat_gpt_service,
            cache_client=self.mock_cache_client
        )

    def make_email(self, snippet="Your Wells Fargo balance is $123.45", message_id="msg1"):
        return GmailEmail({
            'id': message_id,
            'threadId': 'thread1',
            'labelIds': ['INBOX', 'UNREAD'],
            'snippet': snippet,
            'internalDate': str(int(datetime.datetime.now().timestamp() * 1000)),
            'payload': {'headers': []}
        })

    def make_rule(self, bank_key=BankKey.WellsFargo):
        return GmailEmailRule(
            rule_id='rule1',
            name='Test Rule',
            description='desc',
            max_results=1,
            query='balance',
            action='bank-sync',
            data={'bank_sync_bank_key': bank_key},
            created_date=datetime.datetime.now(),
            count_processed=0
        )

    async def test_handle_balance_sync_success(self):
        # Simulate GPT returning a valid balance
        self.mock_chat_gpt_service.get_chat_completion.return_value = ("123.45", 10)
        self.mock_cache_client.get_json.return_value = None
        rule = self.make_rule()
        email = self.make_email()
        # Patch _is_banking_email to always True
        self.service._is_banking_email = MagicMock(return_value=True)
        # Patch _get_chat_gpt_balance_completion to simulate GPT
        self.service._get_chat_gpt_balance_completion = AsyncMock(return_value=MagicMock(balance="123.45", usage=10, is_success=True))
        self.service._handle_account_specific_balance_sync = MagicMock(return_value=BankKey.WellsFargo)
        self.mock_bank_service.capture_balance.return_value = MagicMock()
        result = await self.service.handle_balance_sync(rule, email, BankKey.WellsFargo)
        self.assertIsNotNone(result)
        self.mock_bank_service.capture_balance.assert_awaited()

    async def test_handle_balance_sync_no_banking_keywords(self):
        # Patch _is_banking_email to always False
        self.service._is_banking_email = MagicMock(return_value=False)
        rule = self.make_rule()
        email = self.make_email()
        result = await self.service.handle_balance_sync(rule, email, BankKey.WellsFargo)
        self.assertIsNone(result)

    async def test_handle_balance_sync_balance_not_found(self):
        # Simulate GPT returning DEFAULT_BALANCE
        self.service._is_banking_email = MagicMock(return_value=True)
        self.service._get_chat_gpt_balance_completion = AsyncMock(return_value=MagicMock(balance="undefined", usage=0, is_success=False))
        rule = self.make_rule()
        email = self.make_email()
        result = await self.service.handle_balance_sync(rule, email, BankKey.WellsFargo)
        self.assertIsNone(result)

    async def test_handle_balance_sync_invalid_float(self):
        # Simulate GPT returning a non-float value
        self.service._is_banking_email = MagicMock(return_value=True)
        self.service._get_chat_gpt_balance_completion = AsyncMock(return_value=MagicMock(balance="notanumber", usage=0, is_success=True))
        rule = self.make_rule()
        email = self.make_email()
        result = await self.service.handle_balance_sync(rule, email, BankKey.WellsFargo)
        self.assertIsNone(result)
