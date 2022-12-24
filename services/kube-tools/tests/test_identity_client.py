from clients.identity_client import IdentityClient
from domain.auth import ClientScope
from tests.buildup import ApplicationBase
from framework.clients.cache_client import CacheClientAsync
from framework.di.service_collection import ServiceCollection
from unittest.mock import AsyncMock


class IdentityClientTests(ApplicationBase):
    def configure_services(self, service_collection: ServiceCollection):
        self.mock_cache_client = AsyncMock()

        def get_mock_cache_client(services):
            return self.mock_cache_client

        service_collection.add_singleton(
            dependency_type=CacheClientAsync,
            factory=get_mock_cache_client)

    def get_client(
        self
    ) -> IdentityClient:

        return self.resolve(IdentityClient)

    async def test_get_token_with_scope(self):
        client = self.get_client()

        token = await client.get_token(
            client_name='kube-tools-api',
            scope=ClientScope.AzureGatewayApi)

        self.assertIsNotNone(token)

    async def test_get_token(self):
        client = self.get_client()

        token = await client.get_token(
            client_name='kube-tools-api')

        self.assertIsNotNone(token)
