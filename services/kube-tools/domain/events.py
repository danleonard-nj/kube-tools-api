from datetime import datetime

from azure.servicebus import ServiceBusMessage
from framework.serialization import Serializable
from framework.serialization.utilities import serialize


class ApiMessage(Serializable):
    def __init__(
        self,
        base_url: str,
        method: str,
        token: str
    ):
        self.endpoint = self.get_endpoint(
            base_url=base_url)

        self.method = method
        self.json = self.get_body()
        self.headers = self.get_headers(
            token=token)

    def get_delay(
        _timedelta
    ):
        return None

    def get_body(
        self
    ) -> dict:
        pass

    def get_endpoint(
        self,
        base_url
    ) -> str:
        pass

    def get_headers(
        self,
        token: str
    ) -> str:

        return {
            'Authorization': f'Bearer {token}'
        }

    def to_service_bus_message(
        self
    ) -> ServiceBusMessage:

        message = ServiceBusMessage(
            body=serialize({
                'endpoint': self.endpoint,
                'method': self.method,
                'headers': self.headers,
                'content': self.json
            }))

        if self.get_delay() is not None:
            scheduled = datetime.utcnow() + self.get_delay()
            message.scheduled_enqueue_time_utc = scheduled

        return message


class SendEmailEvent(ApiMessage):
    def __init__(
        self,
        body: dict,
        endpoint: str,
        token: str
    ):
        self.body = body
        self.endpoint = endpoint
        self.token = token

        super().__init__(
            None,
            'POST',
            token)

    def get_body(
        self
    ) -> dict:
        return self.body

    def get_endpoint(
        self,
        base_url: str
    ) -> str:
        return self.endpoint
