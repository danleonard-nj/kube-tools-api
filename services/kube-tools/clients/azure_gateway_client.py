from unicodedata import name
from domain.auth import ClientScope
from domain.azure_gateway import AzureGatewayCacheKey
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger.providers import get_logger
from framework.serialization.utilities import serialize
from utilities.utils import build_url
import httpx

from clients.abstractions.gateway_client import GatewayClient
from clients.identity_client import IdentityClient

logger = get_logger(__name__)


def not_success(status_code):
    return status_code != 200


class AzureGatewayClient(GatewayClient):
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
            client_scope=ClientScope.AzureGatewayApi)

    async def acr_get_manifests(
        self,
        repository_name: str
    ):
        logger.info(f'ACR: get manifests: {repository_name}')

        url = build_url(
            base=f'{self.base_url}/api/azure/acr/manifests',
            repository_name=repository_name)

        headers = await self.get_headers()
        response = await self.http_client.get(
            url=url,
            headers=headers,
            timeout=None)

        return response.json()

    async def acr_delete_manifest(
        self,
        repository_name: str,
        manifest_id: str
    ):
        logger.info(f'ACR: delete manifests: Repository: {repository_name}')
        logger.info(f'ACR: delete manifests: ID: {manifest_id}')

        url = build_url(
            base=f'{self.base_url}/api/azure/acr/manifests',
            repository_name=repository_name,
            manifest_id=manifest_id)

        headers = await self.get_headers()
        response = await self.http_client.delete(
            url=url,
            headers=headers,
            timeout=None)

        logger.info(f'Response: {response.status_code}: {response.text}')
        return response.json()

    async def acr_get_repositories(
        self
    ) -> dict:
        headers = await self.get_headers()
        response = await self.http_client.get(
            url=f'{self.base_url}/api/azure/acr/repositories',
            headers=headers,
            timeout=None)

        logger.info(f'Response {response.status_code}: {response.text}')

        return response.json()

    async def get_pod_images(
        self
    ) -> dict:
        logger.info('ACR: Get pod images')

        headers = await self.get_headers()
        response = await self.http_client.get(
            url=f'{self.base_url}/api/azure/aks/pods/images',
            headers=headers,
            timeout=None)

        return response.json()

    async def usage(
        self,
        **kwargs
    ) -> dict:
        url = build_url(
            base=f'{self.base_url}/api/azure/usage',
            **kwargs)

        cache_key = AzureGatewayCacheKey.usage_key(
            url=url)

        logger.info(f'Fetching usage response from cache: {cache_key}')
        cached_response = await self.__cache_client.get_json(
            key=cache_key)

        if cached_response is not None:
            logger.info('Fetched usage response from cache')
            return cached_response

        headers = await self.get_headers()
        response = await self.http_client.get(
            url=url,
            headers=headers,
            timeout=None)

        content = response.json()

        logger.info('Caching usage response')
        await self.__cache_client.set_json(
            key=cache_key,
            value=serialize(content),
            ttl=60)

        return content

    async def get_cost_management_data(
        self,
        **kwargs
    ) -> dict:
        url = build_url(
            base=f'{self.base_url}/api/azure/cost/timeframe/daily/groupby/product',
            **kwargs)

        headers = await self.get_headers()
        response = await self.http_client.get(
            url=url,
            headers=headers,
            timeout=None)

        content = response.json()
        return content

    async def get_pods(
        self
    ) -> dict:
        url = f'{self.base_url}/api/azure/aks/pods/names'

        headers = await self.get_headers()
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.get(
                url=url,
                headers=headers)

            logger.info(f'Gateway response: {response.status_code}')

            if not_success(response.status_code):
                raise Exception(
                    f'Failed to fetch pods from Azure gateway: {response.text}')

            return response.json()

    async def get_logs(
        self,
        namespace: str,
        pod: str
    ) -> dict:
        url = f'{self.base_url}/api/azure/aks/{namespace}/{pod}/logs'

        headers = await self.get_headers()
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.get(
                url=url,
                headers=headers)

            logger.info(f'Gateway response: {response.status_code}')

            if not_success(response.status_code):
                raise Exception(
                    f'Failed to fetch logs from Azure gateway: {response.text}')

            return response.json()
