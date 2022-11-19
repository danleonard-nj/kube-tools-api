from domain.auth import ClientScope
from framework.clients.cache_client import CacheClientAsync
from clients.identity_client import IdentityClient
from framework.configuration import Configuration
from framework.logger.providers import get_logger

from clients.abstractions.gateway_client import GatewayClient

logger = get_logger(__name__)


class TwilioGatewayClient(GatewayClient):
    def __init__(
        self,
        identity_client: IdentityClient,
        cache_client: CacheClientAsync,
        configuration: Configuration
    ):
        super().__init__(
            configuration=configuration,
            identity_client=identity_client,
            cache_client=cache_client,
            cache_key=self.__class__.__name__,
            client_name='kube-tools-api',
            client_scope=ClientScope.TwilioGatewayApi)

    async def send_sms(
        self,
        recipient: str,
        message: str
    ) -> dict:
        logger.info(f'Sending SMS message to recipient: {recipient}')
        logger.info(f'Message body: {message}')

        endpoint = f'{self.base_url}/api/twilio/message'
        body = {
            'recipient': recipient,
            'message': message
        }

        logger.info(f'Endpoint: {endpoint}')
        headers = await self.get_headers()

        response = await self.http_client.post(
            url=endpoint,
            headers=headers,
            json=body)

        logger.info(f'Response status: {response.status_code}')
        return response.json()
