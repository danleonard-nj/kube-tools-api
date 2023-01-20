from clients.event_client import EventClient
from clients.identity_client import IdentityClient
from domain.auth import ClientScope
from domain.events import SendEmailEvent


class EventService:
    def __init__(
        self,
        event_client: EventClient,
        identity_client: IdentityClient
    ):
        self.__event_client = event_client
        self.__identity_client = identity_client

    async def dispatch_email_event(
        self,
        endpoint,
        message
    ):
        token = await self.__identity_client.get_token(
            client_name='kube-tools-api',
            scope=ClientScope.EmailGatewayApi)

        event = SendEmailEvent(
            body=message,
            endpoint=endpoint,
            token=token)

        self.__event_client.send_message(
            event.to_service_bus_message())
