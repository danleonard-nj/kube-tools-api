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


BankRuleMapping = {
    'e5bec174-12ad-40f1-9413-f8a1e69f2eed': BankKey.Chase,
    '7062d7af-c920-4f2e-bdc5-e52314d69194': 'wells-fargo',
    'bffcec15-f23f-4935-9e5e-50282c264325': 'capital-one'
}


class BankBalance(Serializable):
    def __init__(
        self,
        balance_id: str,
        bank_key: str,
        balance: float,
        timestamp: int,
        gpt_tokens: int = 0,
        message_bk: str = None
    ):
        self.balance_id = balance_id
        self.bank_key = bank_key
        self.balance = balance
        self.gpt_tokens = gpt_tokens
        self.message_bk = message_bk
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
            timestamp=data.get('timestamp'))
