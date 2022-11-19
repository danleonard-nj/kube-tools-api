import json
import uuid
from hashlib import md5

from framework.serialization import Serializable


def generate_key(data):
    serialized = json.dumps(data, default=str)
    hashed = md5(serialized.encode())
    return str(uuid.UUID(hashed.hexdigest()))


class ReverbPrice(Serializable):
    def __init__(
        self,
        amount,
        amount_cents,
        currency
    ):
        self.amount = amount
        self.amount_cents = amount_cents
        self.currency = currency

    @staticmethod
    def from_entity(data):
        return ReverbPrice(
            amount=data.get('amount'),
            amount_cents=data.get('amount_cents'),
            currency=data.get('currency'))

    @staticmethod
    def from_response(data):
        return ReverbPrice(
            amount=data.get('amount'),
            amount_cents=data.get('amount_cents'),
            currency=data.get('currency'))
