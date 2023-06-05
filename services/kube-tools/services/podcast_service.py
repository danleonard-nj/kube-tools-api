import asyncio
import random
from typing import Dict, List, Tuple

import httpx
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger

from clients.email_gateway_client import EmailGatewayClient
from clients.google_drive_client import GoogleDriveClient
from data.podcast_repository import PodcastRepository
from domain.features import Feature
from domain.podcasts import DownloadedEpisode, Episode, Feed, FeedHandler, Show
from services.event_service import EventService

logger = get_logger(__name__)


class PodcastService:
    def __init__(
        self,
        podcast_repository: PodcastRepository,
        google_drive_client: GoogleDriveClient,
        email_gateway_client: EmailGatewayClient,
        event_service: EventService,
        feature_client: FeatureClientAsync,
        configuration: Configuration
    ):
        self.__configuration = configuration
        self.__random_delay = self.__configuration.podcasts.get(
            'random_delay')

        self.__podcast_repository = podcast_repository
        self.__google_drive_client = google_drive_client
        self.__email_gateway_client = email_gateway_client
        self.__feature_client = feature_client
        self.__event_service = event_service

        self.upload_threads = []

    async def sync(
        self
    ) -> dict:
        '''
        Sync podcast feeds
        '''

        feeds = self.get_feeds()
        results = list()

        for feed in feeds:
            logger.info(f'Handling feed: {feed.name}')
            try:
                res = await self.handle_feed(
                    feed=feed)

                # Only return shows with new eps
                if res:
                    results.append(res)
            except Exception as ex:
                # Don't fail every feed for one broken
                # feed
                logger.exception(f'Failed to update show: {str(ex)}')

        return {
            download.show.show_id: download.show.to_dict()
            for download in results if download is not None
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
        await self.__podcast_repository.update(
            values=show.to_dict(),
            selector=show.get_selector())

        # Send an email for the downloaded episodes
        await self.__send_email(
            episodes=downloads)

        return downloads

    def get_feeds(
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

        logger.info(f'{episode.get_filename()}: Upload started')

        # Upload file to Google Drive
        await self.__google_drive_client.upload_file(
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
            'Size': f'{episode.size} mb'
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

        is_enabled = await self.__feature_client.is_enabled(
            feature_key=Feature.PodcastSyncEmailNotify)

        if not is_enabled:
            logger.info('Email notify is disabled')
            return

        if not any(episodes):
            logger.info(f'No episodes downloaded')
            return

        email_request, endpoint = self.__email_gateway_client.get_datatable_email_request(
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

        entity = await self.__podcast_repository.get({
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
