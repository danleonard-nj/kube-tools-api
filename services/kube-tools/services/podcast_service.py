import asyncio
import random
from threading import Semaphore
from typing import Dict, List, Tuple

import httpx
from framework.clients.http_client import HttpClient
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger

from clients.email_gateway_client import EmailGatewayClient
from clients.google_drive_client import GoogleDriveClient
from data.podcast_repository import PodcastRepository
from domain.podcasts import DownloadedEpisode, Episode, Feed, FeedHandler, Show
from services.event_service import EventService
from framework.concurrency import TaskCollection

logger = get_logger(__name__)


class PodcastService:
    def __init__(
        self,
        repository: PodcastRepository,
        drive: GoogleDriveClient,
        email_gateway: EmailGatewayClient,
        event_service: EventService,
        configuration: Configuration
    ):
        self.__configuration = configuration
        self.__random_delay = self.__configuration.podcasts.get(
            'random_delay')

        self.__repository = repository
        self.__drive = drive
        self.__email_gateway = email_gateway
        self.__http_client = HttpClient()
        self.__event_service = event_service

        self.upload_threads = []

    async def sync(
        self
    ) -> dict:
        '''
        Sync podcast feeds
        '''

        # TODO: Figure out a safe value for this
        semaphore = asyncio.Semaphore(1)

        feeds = self.__get_feeds()

        async def handler_wrapper(feed):
            await semaphore.acquire()
            await self.handle_feed(feed=feed)
            semaphore.release()

        sync = TaskCollection(*[
            handler_wrapper(feed=feed)
            for feed in feeds
        ])

        downloads = await sync.run()

        return {
            download.show.show_id: download.show.to_dict()
            for download in downloads if download is not None
        }

    async def handle_feed(
        self,
        feed: Feed
    ):
        logger.info(f'Handling RSS feed: {feed.name}')

        # Get episodes to download and show model
        downloads, show = await self.__sync_feed(
            rss_feed=feed)

        if not any(downloads):
            logger.info(f'No new episodes for show')
            return

        logger.info(
            f'Downloading {len(downloads)} episodes for show')

        # Update the show with new episodes
        await self.__repository.update(
            values=show.to_dict(),
            selector=show.get_selector())

        # Send an email for the downloaded episodes
        await self.__send_email(
            episodes=downloads)

        return downloads

    def __get_feeds(
        self
    ) -> List[Feed]:
        '''
        Get all configured RSS feeds
        '''

        configuration = self.__configuration.podcasts
        return [
            Feed(x) for x in configuration.get('feeds')
        ]

    async def __upload_file(
        self,
        episode: DownloadedEpisode,
        audio: bytes
    ) -> None:
        '''
        Upload podcast audio to Google Drive
        '''

        # TODO: Figure out a safe value for this
        semaphore = Semaphore(1)

        semaphore.acquire()
        logger.info(f'{episode.get_filename()}: Upload started')

        # Upload file to Google Drive
        await self.__drive.upload_file(
            filename=episode.get_filename(),
            data=audio)

        logger.info(f'{episode.get_filename()}: Episode uploaded successfully')
        del audio

    def __get_results_table(
            self,
            episodes: List[Episode]
    ) -> Dict:
        '''
        Get sync result table for email notification
        '''

        return [{
            'Show': episode.show.show_title,
            'Episode': episode.episode.episode_title,
            'Size': episode.size
        } for episode in episodes]

    async def __wait_random_delay(
        self
    ) -> None:
        '''
        Random delay between feed sync
        '''

        logger.info(f'Random delay: {self.__random_delay}')

        if self.__random_delay:
            delay = random.randint(60, 240)
            logger.info(f'Delay: {delay} seconds')

            await asyncio.sleep(delay)

    async def __send_email(
        self,
        episodes: list[DownloadedEpisode]
    ):
        logger.info(f'Sending email for saved episodes')

        if not any(episodes):
            logger.info(f'No episodes downloaded')
            return

        email_request, endpoint = self.__email_gateway.get_datatable_email_request(
            recipient='dcl525@gmail.com',
            subject='Podcast Sync',
            data=self.__get_results_table(episodes))

        await self.__event_service.dispatch_email_event(
            endpoint=endpoint,
            message=email_request.to_dict())

    async def __get_feed_request(
        self,
        rss_feed: Feed
    ):
        '''
        Fetch the RSS feed
        '''

        async with httpx.AsyncClient() as client:
            return await client.get(
                url=rss_feed.feed,
                follow_redirects=True)

    async def __get_episode_audio(
        self,
        episode: Episode
    ):
        async with httpx.AsyncClient(timeout=None) as client:
            return await client.get(
                url=episode.audio,
                follow_redirects=True)

    async def __get_saved_show(
        self,
        show: Show
    ) -> Show:
        '''
        Get the saved show record
        '''

        logger.info(f'Get show entity: {show.show_id}')

        entity = await self.__repository.get({
            'show_id': show.show_id
        })

        # Initial insert if no record for show exists
        if entity is None:
            logger.info(f'Initial insert for show: {show.show_title}')

            return Show(
                show_id=show.show_id,
                show_title=show.show_title,
                episodes=list())

        return Show.from_entity(
            entity=entity)

    async def __sync_feed(
        self,
        rss_feed: Feed
    ) -> Tuple[List[DownloadedEpisode], Show]:

        await self.__wait_random_delay()

        logger.info(f'Fetching RSS feed for show: {rss_feed.name}')

        feed_data = await self.__get_feed_request(
            rss_feed=rss_feed)

        logger.info(f'Parsing show from feed data')
        show = FeedHandler.get_show(
            feed=feed_data.text)

        logger.info(f'Feed episode count: {len(show.episodes)}')

        # Get the stored show
        entity = await self.__get_saved_show(
            show=show)
        logger.info(f'Entity episode count: {len(entity.episodes)}')

        download_queue = []

        for episode in show.episodes:
            if not entity.contains_episode(
                    episode_id=episode.episode_id):

                logger.info(f'Save episode: {episode.episode_title}')

                audio_data = await self.__get_episode_audio(
                    episode=episode)

                logger.info(f'Bytes fetched: {len(audio_data.content)}')

                downloaded_episode = DownloadedEpisode(
                    episode=episode,
                    show=show,
                    size=len(audio_data.content))

                download_queue.append(downloaded_episode)

                await self.__upload_file(
                    episode=downloaded_episode,
                    audio=audio_data.content)

        return (download_queue, show)
