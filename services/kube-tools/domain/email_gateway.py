from framework.serialization import Serializable


class EmailGatewayConstants:
    Me = 'dcl525@gmail.com'


class EmailGatewayRequest(Serializable):
    def __init__(
        self,
        recipient,
        subject,
        body=None,
        table=None,
        json=None
    ):
        self.recipient = recipient
        self.subject = subject

        if body is not None:
            self.body = body
        if table is not None:
            self.table = table
        if json is not None:
            self.json = json
