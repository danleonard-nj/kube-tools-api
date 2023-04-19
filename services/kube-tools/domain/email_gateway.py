from typing import Dict, List

from framework.serialization import Serializable


class EmailGatewayRequest(Serializable):
    def __init__(
        self,
        recipient: str,
        subject: str,
        body: Dict = None,
        table: List[Dict] = None,
        json: Dict = None
    ):
        self.recipient = recipient
        self.subject = subject

        if body is not None:
            self.body = body
        if table is not None:
            self.table = table
        if json is not None:
            self.json = json
