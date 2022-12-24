from datetime import datetime, timedelta
from unittest.mock import AsyncMock

from framework.clients.cache_client import CacheClientAsync
from framework.di.service_collection import ServiceCollection

from clients.azure_gateway_client import AzureGatewayClient
from clients.email_gateway_client import EmailGatewayClient
from clients.twilio_gateway import TwilioGatewayClient
from tests.buildup import ApplicationBase


class TwilioGatewayClientTests(ApplicationBase):
    def configure_services(self, service_collection: ServiceCollection):
        self.mock_cache_client = AsyncMock()

        def get_mock_cache_client(services):
            return self.mock_cache_client

        service_collection.add_singleton(
            dependency_type=CacheClientAsync,
            factory=get_mock_cache_client)

    def get_client(
        self
    ) -> TwilioGatewayClient:
        self.mock_cache_client.get_cache.return_value = None
        return self.resolve(TwilioGatewayClient)

    # async def test_send_sms(self):
    #     client = self.get_client()

    #     response = await client.send_sms(
    #         recipient='+18563323608',
    #         message='test')

    #     self.assertIsNotNone(response)


class EmailGatewayClientTests(ApplicationBase):
    def configure_services(self, service_collection: ServiceCollection):
        self.mock_cache_client = AsyncMock()

        def get_mock_cache_client(services):
            return self.mock_cache_client

        service_collection.add_singleton(
            dependency_type=CacheClientAsync,
            factory=get_mock_cache_client)

    def get_client(
        self
    ) -> EmailGatewayClient:
        self.mock_cache_client.get_cache.return_value = None
        return self.resolve(EmailGatewayClient)

    async def test_send_email(self):
        client = self.get_client()

        response = await client.send_email(
            subject='Test',
            recipient='me@dan-leonard.com',
            message='Test')

        self.assertIsNotNone(response)

    async def test_send_datatable_email(self):
        client = self.get_client()

        data = [{'row': 'value'}]

        response = await client.send_datatable_email(
            subject='Test',
            recipient='me@dan-leonard.com',
            data=data)

        self.assertIsNotNone(response)

    async def test_send_json_email(self):
        client = self.get_client()

        data = [{'row': 'value'}]

        response = await client.send_json_email(
            subject='Test',
            recipient='me@dan-leonard.com',
            data=data)

        self.assertIsNotNone(response)


class AzureGatewayClientTests(ApplicationBase):
    def configure_services(self, service_collection: ServiceCollection):
        self.mock_cache_client = AsyncMock()

        def get_mock_cache_client(services):
            return self.mock_cache_client

        service_collection.add_singleton(
            dependency_type=CacheClientAsync,
            factory=get_mock_cache_client)

    def get_client(
        self
    ) -> AzureGatewayClient:
        self.mock_cache_client.get_cache.return_value = None
        return self.resolve(AzureGatewayClient)

    async def test_get_pod_images(self):
        client = self.get_client()

        response = await client.get_pod_images()

        self.assertIsNotNone(response)

    async def test_get_acr_manifests(self):
        client = self.get_client()

        response = await client.acr_get_manifests(
            repository_name='framework')

        self.assertIsNotNone(response)

    async def test_get_repositories(self):
        client = self.get_client()

        response = await client.acr_get_repositories()

        self.assertIsNotNone(response)

    async def test_get_cost_management_data(self):
        client = self.get_client()

        start_date = datetime.now() - timedelta(days=1)
        end_date = datetime.now()

        response = await client.get_cost_management_data(
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'))

        self.assertIsNotNone(response)

    async def test_get_pods(self):
        client = self.get_client()

        response = await client.get_pods()

        self.assertIsNotNone(response)

    async def test_get_logs(self):
        client = self.get_client()

        pods_response = await client.get_pods()
        pods = pods_response.get('pods')

        response = await client.get_logs(
            namespace=pods[0].get('name'),
            pod=pods[0].get('namespace'))

        self.assertIsNotNone(response)
