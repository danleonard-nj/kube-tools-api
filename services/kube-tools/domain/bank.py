from datetime import datetime
import enum
import json
from typing import Dict, List, Union

from dateutil import parser
from framework.crypto.hashing import sha256
from framework.logger import get_logger
from framework.serialization import Serializable

from utilities.utils import parse

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


class PlaidTransaction(Serializable):
    def __init__(
        self,
        transaction_id: str,
        transaction_type: str,
        bank_key: str,
        account_id: str,
        amount: float,
        categories: List[str],
        date: str,
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
            self.categories = self.__parse_categories(
                categories)

        self.date = self.__parse_date(date)

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
            timestamp or int(self.date.timestamp())
        )

    # def to_dict(self):
    #     return super().to_dict() | {
    #         'transaction_type': str(self.transaction_type),
    #         'channel': str(self.channel),
    #         'categories': [str(category) for category in self.categories],
    #     }

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
        date: Union[str, datetime]
    ) -> datetime:

        if isinstance(date, datetime):
            return date
        else:
            return parser.parse(date)

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
            date=data.get('date'),
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
            date=data.get('datetime') or data.get('date'),
            merchant=data.get('merchant_name'),
            name=data.get('name'),
            channel=data.get('payment_channel'),
            pending=data.get('pending'),
            pf_categories=data.get('personal_finance_category'))


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
