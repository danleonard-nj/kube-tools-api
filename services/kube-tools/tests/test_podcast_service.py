import json
from tests.buildup import ApplicationBase
from framework.di.service_collection import ServiceCollection
from clients.google_drive_client import GoogleDriveClient
from framework.configuration import Configuration
from unittest.mock import AsyncMock
from services.podcast_service import PodcastService
from clients.email_gateway_client import EmailGatewayClient
from tests.helpers import TestHelper
from framework.clients.http_client import HttpClient
from data.podcast_repository import PodcastRepository
from unittest.mock import patch
import xmltodict

helper = TestHelper()


def first(items, func):
    for item in items:
        if func(item) is True:
            return item


class PodcastServiceTestBuildup(ApplicationBase):
    def get_service(self) -> PodcastService:
        return self.resolve(PodcastService)

    def get_mock_drive_client(self, container):
        self.mock_drive_client = AsyncMock()
        return self.mock_drive_client

    def get_mock_configuration(self, container):
        self.mock_podcast_config = helper.get_podcast_config()
        self.mock_configuration = AsyncMock()
        self.mock_configuration.podcasts = self.mock_podcast_config

        return self.mock_configuration

    def get_mock_email_gateway_client(self, container):
        self.mock_email_gateway_client = AsyncMock()
        return self.mock_email_gateway_client

    def get_mock_http_client(self, container):
        self.mock_http_client = AsyncMock()
        return self.mock_http_client

    def configure_services(self, service_collection: ServiceCollection):
        self.mock_drive_client = AsyncMock()

        service_collection.add_singleton(
            dependency_type=GoogleDriveClient,
            factory=self.get_mock_drive_client)

        service_collection.add_singleton(
            dependency_type=Configuration,
            factory=self.get_mock_configuration)

        service_collection.add_singleton(
            dependency_type=EmailGatewayClient,
            factory=self.get_mock_email_gateway_client)

        service_collection.add_singleton(
            dependency_type=HttpClient,
            factory=self.get_mock_http_client)


class PodcastServiceTest(PodcastServiceTestBuildup):
    async def test_get_feeds(self):
        service = self.get_service()

        results = service.__get_feeds()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].feed, 'http://test')
        self.assertEqual(results[0].name, 'test')

    def handle_get(self, *args, **kwargs):
        print(args)
        print(kwargs)

    async def insert_test_show(self, shows):
        repo = self.resolve(PodcastRepository)
        await repo.insert(shows)

    def get_response(self, *args, **kwargs):
        url = kwargs.get('url')

        mock_response = AsyncMock()
        # if url == 'http://test':
        #     mock_response.status_code = 200
        #     mock_response.text = helper.get_feed_xml()

        # else:
        mock_response.status_code = 200
        mock_response.content = b'content'

        return mock_response

    @patch('xmltodict.parse')
    @patch('httpx.AsyncClient.get')
    async def test_sync_when_no_new_episodes(self, mock_get, mock_parse):
        service = self.get_service()

        shows = helper.get_show_entity()
        await self.insert_test_show(shows)

        mock_get.side_effect = self.get_response
        mock_parse.return_value = helper.get_xml_data()

        result = await service.sync()

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 0)

    @patch('xmltodict.parse')
    @patch('httpx.AsyncClient.get')
    async def test_sync_with_new_episode(self, mock_get, mock_parse):
        service = self.get_service()

        async def handle_response(*args, **kwargs):
            mock_response = AsyncMock()

            if kwargs.get('url') == 'http://test':
                mock_response.status_code = 200
                mock_response.text = ''
                mock_response.content = b'test'

            else:
                mock_response.status_code = 200
                mock_response.content = b'test'

            return mock_response

        mock_get.side_effect = handle_response

        show_id = self.guid()
        show_title = self.guid()

        shows = helper.get_show_entity(
            show_id=show_id,
            show_title=show_title)

        episodes = shows.get('episodes')
        episode_list = episodes[1:]
        shows['episodes'] = episode_list
        await self.insert_test_show(shows)

        feed_data = helper.get_xml_data()
        feed_data['rss']['channel']['acast:showId'] = show_id
        feed_data['rss']['channel']['title'] = show_title

        mock_parse.return_value = feed_data

        result = await service.sync()

        self.assertIsNotNone(result)
        self.assertEqual(1, len(result))
