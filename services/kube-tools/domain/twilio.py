from framework.serialization import Serializable


class TwilioSendMessageRequest(Serializable):
    def __init__(
        self,
        recipient: str,
        message: str
    ):
        self.recipient = recipient
        self.message = message
