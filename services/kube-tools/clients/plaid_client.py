

from httpx import AsyncClient
from framework.logger import get_logger
from framework.configuration import Configuration
from framework.serialization import Serializable

logger = get_logger(__name__)


class PlaidBalanceRequest(Serializable):
    def __init__(
        self,
        client_id: str,
        secret: str,
        access_token: str
    ):
        self.client_id = client_id
        self.secret = secret
        self.access_token = access_token


class PlaidClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient
    ):
        self.__base_url = configuration.plaid.get('base_url')
        self.__client_id = configuration.plaid.get('client_id')
        self.__client_secret = configuration.plaid.get('client_secret')

        self.__http_client = http_client

    async def get_balance(
        self,
        access_token: str
    ):
        logger.info(f'Get balance w/ access token: {access_token}')

        endpoint = f'{self.__base_url}/accounts/balance/get'

        req = PlaidBalanceRequest(
            client_id=self.__client_id,
            secret=self.__client_secret,
            access_token=access_token)

        response = await self.__http_client.post(
            url=endpoint,
            json=req.to_dict())

        logger.info(f'Status: {response.status_code}')

        return response.json()
