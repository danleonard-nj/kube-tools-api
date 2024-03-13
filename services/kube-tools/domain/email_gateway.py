from framework.serialization import Serializable
from framework.exceptions.nulls import ArgumentNullException


class EmailGatewayRequest(Serializable):
    def __init__(
        self,
        recipient: str,
        subject: str,
        body: str = None,
        table: list[dict] = None,
        json: dict = None
    ):
        ArgumentNullException.if_none(recipient, 'recipient')
        ArgumentNullException.if_none(subject, 'subject')

        self.recipient = recipient
        self.subject = subject

        if body is not None:
            self.body = body
        if table is not None:
            self.table = table
        if json is not None:
            self.json = json
