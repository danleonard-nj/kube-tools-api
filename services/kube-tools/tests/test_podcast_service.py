import unittest
import uuid

from data.podcast_repository import PodcastRepository
from framework.configuration import Configuration
from domain.podcasts.podcasts import DownloadedEpisode, Episode, Show
from services.podcast_service import PodcastDownloadException, PodcastService
from framework.utilities.iter_utils import first
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

    async def test_upload_file_given_invalid_length_throws_exception(self):
        service: PodcastService = self.provider.resolve(PodcastService)

        audio_data = b'error message'

        episode = Episode(
            episode_id=str(uuid.uuid4()),
            episode_title=str(uuid.uuid4()),
            audio='http://placeholder')

        show = Show(
            show_id=str(uuid.uuid4()),
            show_title=str(uuid.uuid4()),
            episodes=[])

        downloaded_episode = DownloadedEpisode(
            episode=episode,
            show=show,
            size=len(audio_data))

        with self.assertRaises(Exception):
            await service.upload_file(
                downloaded_episode,
                audio_data)

    async def test_get_episode_audio_given_invalid_uri_throws_exception(self):
        service: PodcastService = self.provider.resolve(PodcastService)

        episode = Episode(
            episode_id=str(uuid.uuid4()),
            episode_title=str(uuid.uuid4()),
            audio='https://api.dan-leonard.com/')

        with self.assertRaises(PodcastDownloadException):
            await service.get_episode_audio(
                episode=episode)
