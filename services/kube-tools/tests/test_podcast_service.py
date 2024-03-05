import unittest
import uuid

from data.podcast_repository import PodcastRepository
from framework.configuration import Configuration
from services.podcast_service import PodcastService
from services.torrent_service import first
from utilities.provider import ContainerProvider


def get_data():
    show_id = str(uuid.uuid4())
    episode_id = str(uuid.uuid4())

    data = {
        "show_id": show_id,
        "show_title": "Test Show",
        "episodes": [
            {
                "episode_id": episode_id,
                "episode_title": "Test Episode",
                "audio": "http://placeholder"
            }
        ]
    }

    return (
        data,
        show_id,
        episode_id
    )


def configure_provider(provider):
    provider.resolve(Configuration).mongo = {
        'connection_string': 'mongodb://localhost:27017',
    }


class TestPodcastService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = ContainerProvider.get_service_provider()

        configure_provider(self.provider)

    async def test_sync_podcasts(
        self
    ):
        service: PodcastService = self.provider.resolve(PodcastService)

        service.dry_run = True

        await service.sync()

    async def test_get_podcasts(self):
        # Call the method under test
        service = self.provider.resolve(PodcastService)

        show_id, episode_id = await self.insert_test_data()

        result = await service.get_podcasts()

        show = first(
            result,
            lambda s: s.show_id == show_id,
        )

        episode = first(
            show.episodes,
            lambda e: e.episode_id == episode_id,
        )

        self.assertIsNotNone(result)
        self.assertTrue(len(result) > 0)
        self.assertEqual(show.show_id, show_id)
        self.assertEqual(episode.episode_id, episode_id)

    async def insert_test_data(
        self
    ):
        data, show_id, episode_id = get_data()

        repo: PodcastRepository = self.provider.resolve(PodcastRepository)

        await repo.collection.insert_one(data)

        return show_id, episode_id
