import httpx
from framework.configuration import Configuration
from framework.logger.providers import get_logger

from clients.identity_client import IdentityClient
from domain.auth import ClientScope

logger = get_logger(__name__)


class TwilioGatewayClient:
    def __init__(
        self,
        identity_client: IdentityClient,
        configuration: Configuration
    ):
        self.__identity_client = identity_client
        self.__base_url = configuration.gateway.get('api_gateway_base_url')

    async def __get_auth_headers(
        self
    ):
        logger.info(f'Fetching Twilio gateway auth token')

        token = await self.__identity_client.get_token(
            client_name='kube-tools-api',
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
        logger.info(f'Sending SMS message to recipient: {recipient}')
        logger.info(f'Message body: {message}')

        endpoint = f'{self.__base_url}/api/twilio/message'
        logger.info(f'Endpoint: {endpoint}')

        body = {
            'recipient': recipient,
            'message': message
        }

        logger.info(f'Endpoint: {endpoint}')
        headers = await self.__get_auth_headers()

        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                url=endpoint,
                headers=headers,
                json=body)

        logger.info(f'Response status: {response.status_code}')
        return response.json()
