from typing import Dict

from clients.identity_client import IdentityClient
from domain.auth import AuthClient, ClientScope
from domain.exceptions import AzureGatewayLogRequestException
from framework.configuration import Configuration
from framework.logger.providers import get_logger
from framework.uri import build_url
from httpx import AsyncClient

logger = get_logger(__name__)


def not_success(status_code):
    return status_code != 200


class AzureGatewayClient:
    def __init__(
        self,
        configuration: Configuration,
        identity_client: IdentityClient,
        http_client: AsyncClient
    ):
        self._http_client = http_client
        self._identity_client = identity_client

        self._base_url = configuration.gateway.get('api_gateway_base_url')

    async def __get_auth_headers(
        self
    ):
        logger.info(f'Fetching azure gateway auth token')

        token = await self._identity_client.get_token(
            client_name=AuthClient.KubeToolsApi,
            scope=ClientScope.AzureGatewayApi)

        return {
            'Authorization': f'Bearer {token}'
        }

    async def acr_get_manifests(
        self,
        repository_name: str
    ):
        logger.info(f'ACR: get manifests: {repository_name}')

        url = build_url(
            base=f'{self._base_url}/api/azure/acr/manifests',
            repository_name=repository_name)

        logger.info(f'Endpoint: {url}')

        headers = await self.__get_auth_headers()
        response = await self._http_client.get(
            url=url,
            headers=headers)

        return response.json()

    async def acr_delete_manifest(
        self,
        repository_name: str,
        manifest_id: str
    ):
        logger.info(f'ACR: delete manifests: Repository: {repository_name}')
        logger.info(f'ACR: delete manifests: ID: {manifest_id}')

        url = build_url(
            base=f'{self._base_url}/api/azure/acr/manifests',
            repository_name=repository_name,
            manifest_id=manifest_id)

        logger.info(f'Endpoint: {url}')

        headers = await self.__get_auth_headers()
        response = await self._http_client.delete(
            url=url,
            headers=headers)

        logger.info(f'Response: {response.status_code}')
        return response.json()

    async def acr_get_repositories(
        self
    ) -> Dict:
        endpoint = f'{self._base_url}/api/azure/acr/repositories'
        logger.info(f'Endpoint: {endpoint}')

        headers = await self.__get_auth_headers()
        response = await self._http_client.get(
            url=endpoint,
            headers=headers)

        logger.info(f'Response {response.status_code}')
        return response.json()

    async def get_pod_images(
        self
    ) -> Dict:
        logger.info('ACR: Get pod images')

        endpoint = f'{self._base_url}/api/azure/aks/pods/images'
        logger.info(f'Endpoint: {endpoint}')

        headers = await self.__get_auth_headers()
        response = await self._http_client.get(
            url=endpoint,
            headers=headers)

        return response.json()

    async def get_cost_management_data(
        self,
        **kwargs
    ) -> Dict:
        logger.info(f'Fetching cost management data from Azure gateway')
        logger.info(f'Params: {kwargs}')

        url = build_url(
            base=f'{self._base_url}/api/azure/cost/timeframe/daily/groupby/product',
            **kwargs)

        logger.info(f'Endpoint: {url}')

        headers = await self.__get_auth_headers()
        response = await self._http_client.get(
            url=url,
            headers=headers)

        content = response.json()
        return content

    async def get_pods(
        self
    ) -> Dict:
        url = f'{self._base_url}/api/azure/aks/pods/names'

        logger.info(f'Endpoint: {url}')

        headers = await self.__get_auth_headers()
        response = await self._http_client.get(
            url=url,
            headers=headers)

        logger.info(f'Gateway response: {response.status_code}')

        if not response.is_success:
            raise Exception(
                f'Failed to fetch pods from Azure gateway: {response.text}')

        return response.json()

    async def get_logs(
        self,
        namespace: str,
        pod: str
    ) -> Dict:
        url = f'{self._base_url}/api/azure/aks/{namespace}/{pod}/logs'

        logger.info(f'Endpoint: {url}')

        headers = await self.__get_auth_headers()
        response = await self._http_client.get(
            url=url,
            headers=headers)

        logger.info(f'Gateway response: {response.status_code}')

        if not_success(response.status_code):
            raise AzureGatewayLogRequestException(
                f'Failed to fetch logs from Azure gateway: {response.text}')

        return response.json()
