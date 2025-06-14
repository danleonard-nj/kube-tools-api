import datetime
import unittest
from unittest.mock import AsyncMock, MagicMock

from domain.bank import (CAPITAL_ONE_QUICKSILVER, CAPITAL_ONE_SAVOR,
                         CAPITAL_ONE_VENTURE, SYNCHRONY_AMAZON,
                         SYNCHRONY_GUITAR_CENTER, SYNCHRONY_SWEETWATER)
from domain.enums import BankKey
from domain.google import GmailEmail, GmailEmailRuleModel
from services.gmail_balance_sync_service import GmailBankSyncService
from utilities.utils import fire_task as original_fire_task


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
        return GmailEmailRuleModel(
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

        async def test_format_balance_result(self):
            # Test with dollar sign and comma
            result = self.service._format_balance_result("$1,234.56")
            self.assertEqual(result, "1234.56")

            # Test with multiple numbers in string, should extract first match
            result = self.service._format_balance_result("Balance: $1,234.56. Previous balance was $987.65")
            self.assertEqual(result, "1234.56")

            # Test with no decimal points
            result = self.service._format_balance_result("No numbers with decimals here")
            self.assertEqual(result, "No numbers with decimals here")

        async def test_is_banking_email(self):
            # Mock the inclusion/exclusion keywords
            original_inclusion = BALANCE_EMAIL_INCLUSION_KEYWORDS
            original_exclusion = BALANCE_EMAIL_EXCLUSION_KEYWORDS

            # For testing, temporarily patch the constants
            import domain.bank
            domain.bank.BALANCE_EMAIL_INCLUSION_KEYWORDS = ["balance", "account", "statement"]
            domain.bank.BALANCE_EMAIL_EXCLUSION_KEYWORDS = ["unsubscribe", "marketing"]

            try:
                # Test with enough matching keywords
                result = self.service._is_banking_email("Your account balance is ready to view in your statement", 3)
                self.assertTrue(result)

                # Test with exclusion keyword present
                result = self.service._is_banking_email("Your account balance is ready. Click here to unsubscribe", 3)
                self.assertFalse(result)

                # Test with insufficient matching keywords
                result = self.service._is_banking_email("Your account information", 3)
                self.assertFalse(result)

                # Test with 'balance' missing (required)
                result = self.service._is_banking_email("Your account statement is ready", 2)
                self.assertFalse(result)
            finally:
                # Restore original values
                domain.bank.BALANCE_EMAIL_INCLUSION_KEYWORDS = original_inclusion
                domain.bank.BALANCE_EMAIL_EXCLUSION_KEYWORDS = original_exclusion

        async def test_clean_message_string(self):
            # Test removing special characters
            result = self.service._clean_message_string("Your balance is $123.45! Please check ASAP.")
            self.assertEqual(result, "Your balance is $123.45 Please check ASAP")

            # Test consolidating spaces
            result = self.service._clean_message_string("Too    many    spaces")
            self.assertEqual(result, "Too many spaces")

            # Test truncation
            long_string = "x" * 600
            result = self.service._clean_message_string(long_string)
            self.assertEqual(len(result), 500)

        async def test_get_chat_gpt_balance_prompt(self):
            message = "Your balance is $123.45"
            result = self.service._get_chat_gpt_balance_prompt(message)
            expected = f"{PROMPT_PREFIX}: '{message}'. {PROMPT_SUFFIX}"
            self.assertEqual(result, expected)

        async def test_get_chat_gpt_balance_completion_cached(self):
            # Test with cached response
            self.mock_cache_client.get_json.return_value = {"balance": "123.45", "usage": 10}

            result = await self.service._get_chat_gpt_balance_completion("test prompt")

            self.assertEqual(result.balance, "123.45")
            self.assertEqual(result.usage, 10)
            self.mock_cache_client.get_json.assert_awaited_once()
            self.mock_chat_gpt_service.get_chat_completion.assert_not_awaited()

        async def test_get_chat_gpt_balance_completion_not_cached(self):
            # Test with no cached response
            self.mock_cache_client.get_json.return_value = None
            self.mock_chat_gpt_service.get_chat_completion.return_value = ("123.45", 10)

            result = await self.service._get_chat_gpt_balance_completion("test prompt")

            self.assertEqual(result.balance, "123.45")
            self.assertEqual(result.usage, 10)
            self.mock_cache_client.get_json.assert_awaited_once()
            self.mock_chat_gpt_service.get_chat_completion.assert_awaited_once()

        async def test_handle_account_specific_balance_sync_capital_one(self):
            # Test with CapitalOne bank key
            self.service._get_capital_one_bank_key = MagicMock(return_value=BankKey.CapitalOneSavor)

            result = self.service._handle_account_specific_balance_sync(
                bank_key=BankKey.CapitalOne,
                email_body_segments=["test segment"]
            )

            self.assertEqual(result, BankKey.CapitalOneSavor)
            self.service._get_capital_one_bank_key.assert_called_once()

        async def test_handle_account_specific_balance_sync_synchrony(self):
            # Test with Synchrony bank key
            self.service._get_synchrony_bank_key = MagicMock(return_value=BankKey.SynchronyAmazon)

            result = self.service._handle_account_specific_balance_sync(
                bank_key=BankKey.Synchrony,
                email_body_segments=["test segment"]
            )

            self.assertEqual(result, BankKey.SynchronyAmazon)
            self.service._get_synchrony_bank_key.assert_called_once()

        async def test_handle_account_specific_balance_sync_other_bank(self):
            # Test with other bank key
            result = self.service._handle_account_specific_balance_sync(
                bank_key=BankKey.WellsFargo,
                email_body_segments=["test segment"]
            )

            self.assertEqual(result, BankKey.WellsFargo)

        async def test_get_synchrony_bank_key(self):
            # Setup test cases

            # Test with Amazon keyword
            result = self.service._get_synchrony_bank_key([f"Email with {SYNCHRONY_AMAZON} keyword"])
            self.assertEqual(result, BankKey.SynchronyAmazon)

            # Test with Guitar Center keyword
            result = self.service._get_synchrony_bank_key([f"Email with {SYNCHRONY_GUITAR_CENTER} keyword"])
            self.assertEqual(result, BankKey.SynchronyGuitarCenter)

            # Test with Sweetwater keyword
            result = self.service._get_synchrony_bank_key([f"Email with {SYNCHRONY_SWEETWATER} keyword"])
            self.assertEqual(result, BankKey.SynchronySweetwater)

            # Test with no matching keywords
            result = self.service._get_synchrony_bank_key(["Email with no matching keywords"])
            self.assertEqual(result, BankKey.Synchrony)

        async def test_get_capital_one_bank_key(self):
            # Setup test cases

            # Test with Savor keyword
            result = self.service._get_capital_one_bank_key([f"Email with {CAPITAL_ONE_SAVOR} keyword"])
            self.assertEqual(result, BankKey.CapitalOneSavor)

            # Test with Venture keyword
            result = self.service._get_capital_one_bank_key([f"Email with {CAPITAL_ONE_VENTURE} keyword"])
            self.assertEqual(result, BankKey.CapitalOneVenture)

            # Test with Quicksilver keyword
            result = self.service._get_capital_one_bank_key([f"Email with {CAPITAL_ONE_QUICKSILVER} keyword"])
            self.assertEqual(result, BankKey.CapitalOneQuickSilver)

            # Test with no matching keywords
            result = self.service._get_capital_one_bank_key(["Email with no matching keywords"])
            self.assertEqual(result, BankKey.CapitalOne)

        async def test_fire_cache_gpt_response(self):
            # Patch fire_task to verify it's called with the right parameters
            try:
                # Replace fire_task with a mock
                import utilities.utils
                mock_fire_task = MagicMock()
                utilities.utils.fire_task = mock_fire_task

                self.service._fire_cache_gpt_response("test_key", "123.45", 10)

                # Verify fire_task was called with expected args
                mock_fire_task.assert_called_once()
                call_args = mock_fire_task.call_args[0][0]
                self.assertEqual(call_args.cr_running, True)  # Coroutine is running
            finally:
                # Restore original fire_task
                utilities.utils.fire_task = original_fire_task
