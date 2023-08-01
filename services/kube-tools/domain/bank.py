import enum
import json
from datetime import datetime
from typing import Dict, List, Union

from dateutil import parser
from utilities.utils import parse_timestamp
from framework.crypto.hashing import sha256
from framework.logger import get_logger
from framework.serialization import Serializable

from utilities.utils import DateTimeUtil, parse

logger = get_logger(__name__)


class BankKey(enum.StrEnum):
    WellsFargo = 'wells-fargo'
    WellsFargoChecking = 'wells-fargo-checking'
    WellsFargoActiveCash = 'wells-fargo-active-cash'
    WellsFargoPlatinum = 'wells-fargo-platinum'
    Chase = 'chase'
    CapitalOne = 'capital-one'
    CapitalOneQuickSilver = 'capital-one-quicksilver'
    CapitalOneVenture = 'capital-one-venture'
    CapitalOneSavor = 'capital-one-savorone'
    Discover = 'discover'
    Ally = 'ally'
    AllySavingsAccount = 'ally-savings-account'
    Synchrony = 'synchrony'
    SynchronyAmazon = 'synchrony-amazon'
    SynchronyGuitarCenter = 'synchrony-guitar-center'
    SynchronySweetwater = 'synchrony-sweetwater'

    @classmethod
    def values(
        cls
    ):
        return [x.value for x in cls]


class PlaidTransactionCategory(enum.StrEnum):
    Debit = 'Debit'
    Payroll = 'Payroll'
    Service = 'Service'
    Payment = 'Payment'
    Electric = 'Electric'
    CarDealersAndLeasing = 'Car Dealers and Leasing'
    Hardware_Store = 'Hardware Store'
    Subscription = 'Subscription'
    Shops = 'Shops'
    Withdrawal = 'Withdrawal'
    Credit = 'Credit'
    Credit_Card = 'Credit Card'
    Insurance = 'Insurance'
    TelecommunicationServices = 'Telecommunication Services'
    FoodAndDrink = 'Food and Drink'
    ThirdParty = 'Third Party'
    Restaurants = 'Restaurants'
    Utilities = 'Utilities'
    Rent = 'Rent'
    ATM = 'ATM'
    Transfer = 'Transfer'
    Cable = 'Cable'
    Automotive = 'Automotive'
    Venmo = 'Venmo'
    Financial = 'Financial'
    Interest = 'Interest'
    InterestEarned = 'Interest Earned'
    Deposit = 'Deposit'
    Check = 'Check'
    Undefined = 'Undefined'
    BankFees = 'Bank Fees'


def parse_category(value):
    try:
        return PlaidTransactionCategory(value)
    except:
        logger.info(f'Failed to parse plaid transaction category: {value}')
        return PlaidTransactionCategory.Undefined


class PlaidPaymentChannel(enum.StrEnum):
    InStore = 'in store'
    Online = 'online'
    Other = 'other'


class PlaidTransactionType(enum.StrEnum):
    Special = 'special'
    Place = 'place'


class SyncActionType(enum.StrEnum):
    Insert = 'insert'
    Update = 'update'
    NoAction = 'no-action'


class PlaidTransaction(Serializable):
    def __init__(
        self,
        transaction_id: str,
        transaction_type: str,
        transaction_date: str,
        bank_key: str,
        account_id: str,
        amount: float,
        categories: List[str],
        merchant: str,
        name: str,
        channel: str,
        pending: bool,
        pf_categories: List[str],
        hash_key: str = None,
        timestamp: int = None
    ):
        self.transaction_id = transaction_id

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
            hash_key or self.__generate_hash_key()
        )

        self.timestamp = (
            timestamp or DateTimeUtil.timestamp()
        )

    def get_selector(
        self
    ) -> Dict:

        return {
            'bank_key': self.bank_key,
            'transaction_id': self.transaction_id
        }

    def __generate_hash_key(
        self
    ):
        data = json.dumps(self.to_dict(), default=str)
        return sha256(data)

    def __parse_date(
        self,
        date: Union[str, datetime, int]
    ) -> int:

        if isinstance(date, datetime):
            return int(date.timestamp())

        if isinstance(date, int):
            return date

        return int(parser.parse(date).timestamp())

    def __parse_categories(
        self,
        categories: List[str]
    ):
        parsed = []
        for category in categories:
            result = parse_category(
                value=category)

            parsed.append(result)

        return parsed

    @staticmethod
    def from_entity(
        data: Dict
    ):
        return PlaidTransaction(
            transaction_id=data.get('transaction_id'),
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
            timestamp=data.get('timestamp'))

    @staticmethod
    def from_plaid_transaction_item(
        data: Dict,
        bank_key: str
    ):
        return PlaidTransaction(
            transaction_id=data.get('transaction_id'),
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
            timestamp=DateTimeUtil.timestamp())


class SyncResult(Serializable):
    def __init__(
        self,
        transaction: PlaidTransaction,
        action: SyncActionType
    ):
        self.transaction = transaction
        self.action = action


class BankRuleConfiguration(Serializable):
    def __init__(
        self,
        rule_name: str,
        bank_key: str,
        alert_type: bool = 'none'
    ):
        self.rule_name = rule_name
        self.bank_key = bank_key
        self.alert_type = alert_type

    @staticmethod
    def from_json_object(
        data: Dict
    ):
        return BankRuleConfiguration(
            rule_name=data.get('rule_name'),
            bank_key=data.get('bank_key'),
            alert_type=data.get('alert_type'))


class SyncType(enum.StrEnum):
    Email = 'email'
    Plaid = 'plaid'


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
        data: Dict
    ):
        self.account_name = data.get('name')

        balances = data.get('balances')

        self.current_balance = balances.get('current')
        self.available_balance = balances.get('available')


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


class PlaidWebhookData(Serializable):
    def __init__(
        self,
        request_id: str,
        data: Dict,
        timestamp: int
    ):
        self.request_id = request_id
        self.data = data
        self.timestamp = timestamp
