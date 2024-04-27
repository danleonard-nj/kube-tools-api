import json
from datetime import datetime
from typing import Dict, List, Union

from domain.enums import (BankKey, PlaidPaymentChannel, PlaidTransactionType,
                          SyncActionType)
from framework.crypto.hashing import sha256
from framework.logger import get_logger
from framework.serialization import Serializable
from utilities.utils import DateTimeUtil, parse, parse_timestamp

logger = get_logger(__name__)


PROMPT_PREFIX = 'Get the current available bank balance (if present) from this string'
PROMPT_SUFFIX = 'Respond with only the balance or "N/A"'

CAPITAL_ONE_SAVOR = 'savor'
CAPITAL_ONE_QUICKSILVER = 'quicksilver'
CAPITAL_ONE_VENTURE = 'venture'

SYNCHRONY_AMAZON = 'prime store card'
SYNCHRONY_GUITAR_CENTER = 'guitar center'
SYNCHRONY_SWEETWATER = 'sweetwater sound'

DEFAULT_BALANCE = 'undefined'

BALANCE_EMAIL_INCLUSION_KEYWORDS = [
    'balance',
    'bank',
    'wells',
    'fargo',
    'chase',
    'discover',
    'account',
    'summary'
    'activity',
    'transactions',
    'credit',
    'card'
]

BALANCE_EMAIL_EXCLUSION_KEYWORDS = [
]

BALANCE_EMAIL_RECIPIENT = 'dcl525@gmail.com'
BALANCE_EMAIL_SUBJECT = 'Bank Balance Captured'
TRANSACTION_DEFAULT_LOOKBACK_DAYS = 3


# Unsupported bank keys for balance captures
BALANCE_BANK_KEY_EXCLUSIONS = [
    BankKey.CapitalOne,
    BankKey.Ally,
    BankKey.Synchrony,
    BankKey.WellsFargoActiveCash,
    BankKey.WellsFargoChecking,
    BankKey.WellsFargoPlatinum,
    BankKey.Discover
]


def format_datetime(dt):
    logger.info(f'Formatting datetime: {dt}')
    return dt.strftime('%Y-%m-%d')


class PlaidBalanceRequest(Serializable):
    def __init__(
        self,
        client_id: str,
        secret: str,
        access_token: str
    ):
        self.client_id = client_id
        self.secret = secret
        self.access_token = access_token


class PlaidTransactionRequestOptions(Serializable):
    def __init__(
        self,
        count: int = 500,
        include_personal_finance_category: bool = True,
        account_ids: List[str] = None,
    ):
        self.count = count
        self.include_personal_finance_category = include_personal_finance_category

        if account_ids is not None:
            self.account_ids = account_ids


class PlaidTransactionsRequest(Serializable):
    def __init__(
        self,
        client_id: str,
        secret: str,
        access_token: str,
        start_date: str,
        end_date: str,
        options: Union[PlaidTransactionRequestOptions, Dict] = None
    ):
        self.client_id = client_id
        self.secret = secret
        self.access_token = access_token
        self.start_date = start_date
        self.end_date = end_date

        if options is not None:
            if isinstance(options, PlaidTransactionRequestOptions):
                self.options = options.to_dict()
            else:
                self.options = options


class GetBalancesResponse(Serializable):
    def __init__(
        self,
        balances: List[Dict],
    ):
        self.balances = balances


class PlaidTransaction(Serializable):
    def __init__(
        self,
        transaction_bk: str,
        transaction_type: str,
        transaction_date: str,
        bank_key: str,
        account_id: str,
        amount: float,
        categories: list[str],
        merchant: str,
        name: str,
        channel: str,
        pending: bool,
        pf_categories: list[str],
        transaction_id: str = None,
        hash_key: str = None,
        last_operation: str = None,
        timestamp: int = None,
        data: Dict = None
    ):
        self.transaction_id = transaction_id
        self.transaction_bk = transaction_bk
        self.last_operation = last_operation

        self.transaction_type = parse(
            transaction_type,
            PlaidTransactionType)

        self.account_id = account_id
        self.bank_key = bank_key
        self.amount = float(amount)

        if any(categories):
            self.categories = categories

        transaction_timestamp = parse_timestamp(
            value=transaction_date)

        self.transaction_date = transaction_timestamp
        self.transaction_iso = datetime.fromtimestamp(
            transaction_timestamp).isoformat()

        self.merchant = merchant
        self.name = name

        self.channel = parse(
            channel,
            PlaidPaymentChannel)

        self.pending = pending
        self.pf_categories = pf_categories

        self.hash_key = (
            hash_key or self._generate_hash_key()
        )

        self.data = data or dict()

        self.timestamp = (
            timestamp or DateTimeUtil.timestamp()
        )

    def get_selector(
        self
    ) -> Dict:

        return {
            'bank_key': self.bank_key,
            'transaction_bk': self.transaction_bk
        }

    def _generate_hash_key(
        self
    ):
        data = json.dumps(self.to_dict(), default=str)
        return sha256(data)

    @staticmethod
    def from_entity(
        data: Dict
    ):
        return PlaidTransaction(
            transaction_id=data.get('transaction_id'),
            transaction_bk=data.get('transaction_bk'),
            transaction_type=data.get('transaction_type'),
            bank_key=data.get('bank_key'),
            account_id=data.get('account_id'),
            amount=data.get('amount'),
            categories=data.get('categories'),
            transaction_date=data.get('transaction_date'),
            merchant=data.get('merchant'),
            name=data.get('name'),
            channel=data.get('channel'),
            pending=data.get('pending'),
            pf_categories=data.get('pf_categories'),
            hash_key=data.get('hash_key'),
            last_operation=data.get('last_operation'),
            data=data.get('data'),
            timestamp=data.get('timestamp'))

    @staticmethod
    def from_plaid_transaction_item(
        data: Dict,
        bank_key: str,
    ):
        return PlaidTransaction(
            transaction_bk=data.get('transaction_id'),
            transaction_type=data.get('transaction_type'),
            bank_key=bank_key,
            account_id=data.get('account_id'),
            amount=data.get('amount'),
            categories=data.get('category'),
            transaction_date=data.get('datetime') or data.get('date'),
            merchant=data.get('merchant_name'),
            name=data.get('name'),
            channel=data.get('payment_channel'),
            pending=data.get('pending'),
            pf_categories=data.get('personal_finance_category'),
            last_operation='sync',
            data=data,
            timestamp=DateTimeUtil.timestamp())


class SyncResult(Serializable):
    def __init__(
        self,
        transaction: PlaidTransaction,
        action: SyncActionType,
        original_transaction: PlaidTransaction = None
    ):
        self.action = action
        self.original_transaction = original_transaction
        self.transaction = transaction


class BankBalance(Serializable):
    def __init__(
        self,
        balance_id: str,
        bank_key: str,
        balance: float,
        timestamp: int,
        gpt_tokens: int = 0,
        message_bk: str = None,
        sync_type: str = None
    ):
        self.balance_id = balance_id
        self.bank_key = bank_key
        self.balance = balance
        self.gpt_tokens = gpt_tokens
        self.message_bk = message_bk
        self.sync_type = sync_type
        self.timestamp = timestamp

    @staticmethod
    def from_entity(
        data: Dict
    ):
        return BankBalance(
            balance_id=data.get('balance_id'),
            bank_key=data.get('bank_key'),
            balance=data.get('balance'),
            gpt_tokens=data.get('gpt_tokens'),
            message_bk=data.get('message_bk'),
            sync_type=data.get('sync_type'),
            timestamp=data.get('timestamp'))


class PlaidBalance(Serializable):
    def __init__(
        self,
        account_name: str,
        current_balance: float,
        available_balance: float
    ):
        self.account_name = account_name
        self.current_balance = current_balance
        self.available_balance = available_balance

    @staticmethod
    def from_plaid_response(
        data: Dict
    ):
        balances = data.get('balances')

        return PlaidBalance(
            account_name=data.get('name'),
            current_balance=balances.get('current'),
            available_balance=balances.get('available'))


class PlaidAccount:
    @property
    def sync_threshold_seconds(
        self
    ):
        return self.sync_threshold_minutes * 60

    def __init__(
        self,
        bank_key: str,
        access_token: str,
        account_id: str,
        sync_threshold_minutes: int = 60
    ):
        self.bank_key = bank_key
        self.access_token = access_token
        self.account_id = account_id
        self.sync_threshold_minutes = sync_threshold_minutes

    @staticmethod
    def from_configuration(data):
        return PlaidAccount(
            bank_key=data.get('bank_key'),
            access_token=data.get('access_token'),
            account_id=data.get('account_id'),
            sync_threshold_minutes=data.get('sync_threshold_minutes'))


class ChatGptBalanceCompletion(Serializable):
    def __init__(
        self,
        balance: float,
        usage: int,
        is_success: bool
    ):
        self.balance = balance
        self.usage = usage
        self.is_success = is_success

    @staticmethod
    def from_balance_response(
        balance: float,
        usage: int
    ):
        return ChatGptBalanceCompletion(
            balance=balance,
            usage=usage,
            is_success=balance != 'N/A'
        )
