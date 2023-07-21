import enum
from typing import Dict

from framework.serialization import Serializable


class BankKey(enum.StrEnum):
    WellsFargo = 'wells-fargo'
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


class BankRuleConfig(Serializable):
    def __init__(
        self,
        rule_name: str,
        bank_key: str
    ):
        self.rule_name = rule_name
        self.bank_key = bank_key

    @staticmethod
    def from_json_object(
        data: Dict
    ):
        return BankRuleConfig(
            rule_name=data.get('rule_name'),
            bank_key=data.get('bank_key'))


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

    def get_formatted_bank_key(
        self,
        bank_key: str
    ):
        name = self.account_name.lower()
        name = name.replace(' ', '-')

        return f'{bank_key}-{name}'
