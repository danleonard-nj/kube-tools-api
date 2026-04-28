from clients.event_client import EventClient
from clients.identity_client import IdentityClient
from domain.auth import AuthClient, ClientScope
from domain.events import ApiMessage, SendEmailEvent, TranscriptionArchiveEvent
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

logger = get_logger(__name__)

TRANSCRIPTIONS_ENDPOINT = "/api/tools/transcription/internal/archive"

class EventService:
    def __init__(
        self,
        configuration: Configuration,
        event_client: EventClient,
        identity_client: IdentityClient
    ):
        self._event_client = event_client
        self._identity_client = identity_client
        self._self_base_url = configuration.gateway.get(
            'api_gateway_base_url')

    async def dispatch_event(
        self,
        event: ApiMessage,
    ):
        ArgumentNullException.if_none(event, 'event')

        logger.info(f'Emit event: {event.endpoint}')

        self._event_client.send_message(
            event.to_service_bus_message())

    async def dispatch_email_event(
        self,
        endpoint: str,
        message: str
    ) -> None:

        ArgumentNullException.if_none_or_whitespace(endpoint, 'endpoint')
        ArgumentNullException.if_none_or_whitespace(message, 'message')

        logger.info(f'Emit email notification event: {endpoint}')

        token = await self._identity_client.get_token(
            client_name=AuthClient.KubeToolsApi,
            scope=ClientScope.EmailGatewayApi)

        event = SendEmailEvent(
            body=message,
            endpoint=endpoint,
            token=token)

        self._event_client.send_message(
            event.to_service_bus_message())

    async def dispatch_transcription_archive(
        self,
        transcription_id: str,
        upload_id: str,
    ) -> None:
        """Fan out an async archive job for a completed transcription.

        The relay function will POST back to this service's internal
        ``/api/transcription/internal/archive`` endpoint with a fresh
        bearer token, where the worker fetches the upload bytes by
        ``upload_id``, encodes Opus, and writes both the audio and the
        overlay PNG to GridFS.
        """
        ArgumentNullException.if_none_or_whitespace(
            transcription_id, 'transcription_id')
        ArgumentNullException.if_none_or_whitespace(upload_id, 'upload_id')

        token = await self._identity_client.get_token(
            client_name=AuthClient.KubeToolsApi,
            scope=ClientScope.KubeToolsApi)

        endpoint = (
            f"{self._self_base_url.rstrip('/')}"
            f"{TRANSCRIPTIONS_ENDPOINT}"
        )

        event = TranscriptionArchiveEvent(
            transcription_id=transcription_id,
            upload_id=upload_id,
            endpoint=endpoint,
            token=token)

        logger.info(
            f'Dispatching transcription archive event tx={transcription_id} '
            f'upload={upload_id}')

        self._event_client.send_message(
            event.to_service_bus_message())
