from typing import Dict
from framework.serialization import Serializable
from decimal import Decimal, ROUND_HALF_UP


GROUP_BY_AGGS = {
    'usd_amount': 'sum',
    'usd_exchange': 'first',
    'balance': 'sum'
}


def round_currency(amount, precision='0.01'):
    amount = Decimal(amount).quantize(
        exp=Decimal(precision),
        rounding=ROUND_HALF_UP)

    return float(amount)


class CoinbaseAccount(Serializable):
    @property
    def usd_amount(self) -> float:
        return self.balance * self.usd_exchange

    def __init__(
        self,
        account_id: str,
        account_name: str,
        balance: float,
        currency_code: str,
        currency_name: str,
        usd_exchange: float = None
    ):
        self.account_id = account_id
        self.account_name = account_name
        self.balance = balance
        self.currency_code = currency_code
        self.currency_name = currency_name
        self.usd_exchange = usd_exchange

    @staticmethod
    def from_coinbase_api(
        data: dict
    ) -> 'CoinbaseAccount':

        balance = float(data.get('balance').get('amount'))

        return CoinbaseAccount(
            account_id=data.get('id'),
            account_name=data.get('name'),
            balance=balance,
            currency_code=data.get('currency').get('code'),
            currency_name=data.get('currency').get('name'))

    def to_dict(self) -> Dict:
        return super().to_dict() | {
            'usd_amount': self.usd_amount
        }
