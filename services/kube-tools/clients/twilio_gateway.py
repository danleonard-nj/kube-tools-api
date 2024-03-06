from clients.identity_client import IdentityClient
from domain.auth import AuthClient, ClientScope
from domain.twilio import TwilioSendMessageRequest
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from httpx import AsyncClient

logger = get_logger(__name__)


class TwilioGatewayClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        identity_client: IdentityClient
    ):
        self._http_client = http_client
        self._identity_client = identity_client
        self._base_url = configuration.gateway.get('api_gateway_base_url')

    async def _get_auth_headers(
        self
    ):
        logger.info(f'Fetching Twilio gateway auth token')

        token = await self._identity_client.get_token(
            client_name=AuthClient.KubeToolsApi,
            scope=ClientScope.TwilioGatewayApi)

        logger.info(f'Twilio gateway token: {token}')

        return {
            'Authorization': f'Bearer {token}'
        }

    async def send_sms(
        self,
        recipient: str,
        message: str
    ) -> dict:

        ArgumentNullException.if_none_or_whitespace(recipient, 'recipient')
        ArgumentNullException.if_none_or_whitespace(message, 'message')

        logger.info(f'Sending SMS message to recipient: {recipient}')
        logger.info(f'Message body: {message}')

        endpoint = f'{self._base_url}/api/twilio/message'
        logger.info(f'Endpoint: {endpoint}')

        req = TwilioSendMessageRequest(
            recipient=recipient,
            message=message)

        logger.info(f'Endpoint: {endpoint}')
        headers = await self._get_auth_headers()

        response = await self._http_client.post(
            url=endpoint,
            headers=headers,
            json=req.to_dict())

        logger.info(f'Response status: {response.status_code}')
        return response.json()
