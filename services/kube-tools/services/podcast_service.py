import asyncio
import random
from threading import Semaphore
from typing import List, Tuple

from framework.clients.http_client import HttpClient
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger

from clients.email_gateway_client import EmailGatewayClient
from clients.google_drive_client import GoogleDriveClient
from data.podcast_repository import PodcastRepository
from domain.podcasts import DownloadedEpisode, Episode, Feed, FeedHandler, Show
import httpx

logger = get_logger(__name__)


class PodcastService:
    def __init__(
        self,
        repository: PodcastRepository,
        drive: GoogleDriveClient,
        email_gateway: EmailGatewayClient,
        configuration: Configuration
    ):
        self.__configuration = configuration
        self.__random_delay = self.__configuration.podcasts.get(
            'random_delay')

        self.__repository = repository
        self.__drive = drive
        self.__email_gateway = email_gateway
        self.__http_client = HttpClient()

        self.upload_threads = []

    def get_feeds(
        self
    ) -> List[Feed]:
        '''
        Get all configured RSS feeds

        Returns:
            List[Feed]: List of RSS feeds
        '''

        configuration = self.__configuration.podcasts
        return [
            Feed(x) for x in configuration.get('feeds')
        ]

    async def sync(
        self
    ) -> dict:
        '''
        Sync podcast feeds

        Returns:
            dict: show downloads
        '''

        update_queue = []
        downloads_all = []

        for feed in self.get_feeds():
            logger.info(f'{feed.name}')

            downloads, show = await self.sync_feed(
                rss_feed=feed)
            downloads_all.extend(downloads)

            logger.info(f'Queueing show for update')
            update_queue.append(show)

            if any(downloads):
                logger.info(
                    f'Downloading {len(downloads)} episodes for show')

                selector = {
                    'show_id': show.show_id
                }

                update_result = await self.__repository.update(
                    values=show.to_dict(),
                    selector=selector)

                logger.info(
                    f'Update result: {update_result.matched_count}:{update_result.modified_count}')

                await self.send_email(
                    episodes=downloads)

        return {
            download.show.show_id: download.show.to_dict()
            for download in downloads
        }

    async def upload_file(
        self,
        episode: DownloadedEpisode,
        audio: bytes
    ) -> None:
        '''
        Upload podcast audio to Google Drive

        Args:
            episode (DownloadedEpisode): episode
            audio (bytes): download audio
        '''

        semaphore = Semaphore(3)
        logger.info(f'{episode.get_filename()}: Acquiring thread')

        semaphore.acquire()
        logger.info(f'{episode.get_filename()}: Thread acquired')

        logger.info(f'{episode.get_filename()}: Uploade started')

        await self.__drive.upload_file(
            filename=episode.get_filename(),
            data=audio)

        logger.info(f'{episode.get_filename()}: Episode uploaded successfully')

        del audio

    def __get_results_table(
            self,
            episodes: List[Episode]
    ) -> dict:
        '''
        Get sync result table for email notification

        Args:
            episodes (List[Episode]): podcast episodes

        Returns:
            dict: _description_
        '''

        return [
            {
                'Show': episode.show.show_title,
                'Episode': episode.episode.episode_title,
                'Size': episode.size
            } for episode in episodes
        ]

    async def wait_random_delay(
        self
    ) -> None:

        logger.info(f'Random delay: {self.__random_delay}')

        if self.__random_delay:
            delay = random.randint(60, 240)
            logger.info(f'Delay: {delay} seconds')

            await asyncio.sleep(delay)

    async def send_email(
        self,
        episodes: list[DownloadedEpisode]
    ):
        logger.info(f'Sending email for saved episodes')

        if not any(episodes):
            logger.info(f'No episodes downloaded')

        else:
            await self.__email_gateway.send_datatable_email(
                recipient='dcl525@gmail.com',
                subject='Podcast Sync',
                data=self.__get_results_table(episodes))

    async def get_saved_shows(
        self,
        show: Show
    ) -> Show:
        logger.info(f'Get show entity: {show.show_id}')

        entity = await self.__repository.get({
            'show_id': show.show_id
        })

        if entity is None:
            logger.info(f'Initial insert for show: {show.show_title}')
            return Show(
                show_id=show.show_id,
                show_title=show.show_title,
                episodes=list())

        return Show.from_entity(
            entity=entity)

    async def sync_feed(
        self,
        rss_feed: Feed
    ) -> Tuple[List[DownloadedEpisode], Show]:
        await self.wait_random_delay()

        logger.info(f'Fetching RSS feed for show: {rss_feed.name}')

        async with httpx.AsyncClient() as client:
            feed_data = await client.get(
                url=rss_feed.feed,
                follow_redirects=True)

        logger.info(f'Feed status: {feed_data.status_code}')

        logger.info(f'Parsing show from feed data')
        show = FeedHandler.get_show(
            feed=feed_data.text)

        logger.info(f'Feed episode count: {len(show.episodes)}')
        entity = await self.get_saved_shows(
            show=show)
        logger.info(f'Entity episode count: {len(entity.episodes)}')

        download_queue = []
        for episode in show.episodes:
            if not entity.contains_episode(
                    episode_id=episode.episode_id):

                logger.info(f'Save episode: {episode.episode_title}')

                async with httpx.AsyncClient(timeout=None) as client:
                    audio_data = await client.get(
                        url=episode.audio,
                        follow_redirects=True)

                logger.info(f'Bytes fetched: {len(audio_data.content)}')
                downloaded_episode = DownloadedEpisode(
                    episode=episode,
                    show=show,
                    size=len(audio_data.content))
                download_queue.append(downloaded_episode)

                await self.upload_file(
                    episode=downloaded_episode,
                    audio=audio_data.content)

        return (download_queue, show)
