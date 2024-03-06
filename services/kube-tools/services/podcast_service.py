import asyncio
import random
from typing import Dict, List, Tuple

import httpx
from clients.email_gateway_client import EmailGatewayClient
from clients.google_drive_client import GoogleDriveClient
from data.podcast_repository import PodcastRepository
from domain.exceptions import PodcastConfigurationException
from domain.features import Feature
from domain.podcasts.handlers import (AcastFeedHandler, FeedHandler,
                                      GenericFeedHandler)
from domain.podcasts.podcasts import DownloadedEpisode, Episode, Feed, Show
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from services.event_service import EventService
from utilities.utils import DateTimeUtil

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
        self._configuration = configuration
        self._random_delay = self._configuration.podcasts.get(
            'random_delay')

        self._podcast_repository = podcast_repository
        self._google_drive_client = google_drive_client
        self._email_gateway_client = email_gateway_client
        self._feature_client = feature_client
        self._event_service = event_service

        self.dry_run = False

    async def get_podcasts(
        self
    ) -> List[Show]:
        entities = await self._podcast_repository.get_all()

        shows = [Show.from_entity(x) for x in entities]
        logger.info(f'Found {len(shows)} shows')

        return shows

    async def sync(
        self
    ) -> dict:
        '''
        Sync podcast feeds
        '''

        # Get a list of feeds to sync
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

        return dict()

    async def handle_feed(
        self,
        feed: Feed
    ):
        ArgumentNullException.if_none(feed, 'feed')

        logger.info(f'Handling RSS feed: {feed.name}')

        # Get episodes to download and show model
        downloads, show, is_new = await self._sync_feed(
            rss_feed=feed)

        if not any(downloads):
            logger.info(f'No new episodes for show')
            return

        if not is_new:
            # Update the show modified date
            show.modified_date = DateTimeUtil.timestamp()

            # Update the show with new episodes
            await self._podcast_repository.update(
                selector=show.get_selector(),
                values=show.to_dict()
            )

        # Send an email for the downloaded episodes
        await self._send_email(
            episodes=downloads)

        return downloads

    def get_feeds(
        self
    ) -> List[Feed]:
        '''
        Get all configured RSS feeds
        '''

        configuration = self._configuration.podcasts

        if configuration is None:
            raise PodcastConfigurationException(
                'No podcast configuration found')

        return [
            Feed(x) for x in configuration.get('feeds')
        ]

    async def _upload_file(
        self,
        episode: DownloadedEpisode,
        audio: bytes
    ) -> None:
        '''
        Upload podcast audio to Google Drive
        '''

        ArgumentNullException.if_none(episode, 'episode')
        ArgumentNullException.if_none(audio, 'audio')

        logger.info(f'{episode.get_filename()}: Upload started')

        # Upload file to Google Drive
        await self._google_drive_client.upload_file(
            filename=episode.get_filename(),
            data=audio)

        logger.info(f'{episode.get_filename()}: Episode uploaded successfully')
        del audio

    def _get_results_table(
            self,
            episodes: List[DownloadedEpisode]
    ) -> Dict:
        '''
        Get sync result table for email notification
        '''

        ArgumentNullException.if_none(episodes, 'episodes')

        return [episode.to_result() for episode in episodes]

    async def _wait_random_delay(
        self
    ) -> None:
        '''
        Random delay between feed sync
        '''

        logger.info(f'Random delay: {self._random_delay}')

        if self._random_delay:
            delay = random.randint(60, 240)
            logger.info(f'Delay: {delay} seconds')

            await asyncio.sleep(delay)

    async def _send_email(
        self,
        episodes: list[DownloadedEpisode]
    ):
        ArgumentNullException.if_none(episodes, 'episodes')

        logger.info(f'Sending email for saved episodes')

        is_enabled = await self._feature_client.is_enabled(
            feature_key=Feature.PodcastSyncEmailNotify)

        if not is_enabled:
            logger.info('Email notify is disabled')
            return

        if not any(episodes):
            logger.info(f'No episodes downloaded')
            return

        email_request, endpoint = self._email_gateway_client.get_datatable_email_request(
            recipient='dcl525@gmail.com',
            subject='Podcast Sync',
            data=self._get_results_table(episodes))

        await self._event_service.dispatch_email_event(
            endpoint=endpoint,
            message=email_request.to_dict())

    async def _get_feed_request(
        self,
        rss_feed: Feed
    ):
        '''
        Fetch the RSS feed
        '''

        ArgumentNullException.if_none(rss_feed, 'rss_feed')

        async with httpx.AsyncClient(timeout=None) as client:
            return await client.get(
                url=rss_feed.feed,
                follow_redirects=True)

    async def _get_episode_audio(
        self,
        episode: Episode
    ):
        ArgumentNullException.if_none(episode, 'episode')

        async with httpx.AsyncClient(timeout=None) as client:
            return await client.get(
                url=episode.audio,
                follow_redirects=True)

    async def _get_saved_show(
        self,
        show: Show
    ) -> Tuple[Show, bool]:
        '''
        Get the saved show record
        '''
        ArgumentNullException.if_none(show, 'show')

        logger.info(f'Get show entity: {show.show_id}')

        entity = await self._podcast_repository.get({
            'show_id': show.show_id
        })

        # Initial insert if no record for show exists
        if entity is None:
            logger.info(f'Initial insert for show: {show.show_title}')

            new_show = Show(
                show_id=show.show_id,
                show_title=show.show_title,
                episodes=list())

            result = await self._podcast_repository.insert(
                document=new_show.to_dict())

            logger.info(f'Insert result: {result.inserted_id}')

            return (new_show, True)

        saved_show = Show.from_entity(
            entity=entity)

        return (saved_show, False)

    def _get_handler(
        self,
        handler_type: str
    ) -> FeedHandler:

        ArgumentNullException.if_none_or_whitespace(
            handler_type, 'handler_type')

        if handler_type == 'rss-acast':
            return AcastFeedHandler()
        elif handler_type == 'rss-generic':
            return GenericFeedHandler()
        else:
            raise PodcastConfigurationException(
                f'Unsupported feed type: {handler_type}')

    async def _sync_feed(
        self,
        rss_feed: Feed
    ) -> Tuple[List[DownloadedEpisode], Show]:

        ArgumentNullException.if_none(rss_feed, 'rss_feed')

        await self._wait_random_delay()

        logger.info(f'Fetching RSS feed for show: {rss_feed.name}')

        feed_data = await self._get_feed_request(
            rss_feed=rss_feed)

        logger.info(f'Parsing show from feed data')

        # Get the correct handler for given feed type
        handler = self._get_handler(
            handler_type=rss_feed.type)

        show = handler.get_show(
            feed=feed_data.text)

        logger.info(f'Feed episode count: {len(show.episodes)}')

        # Get the stored show
        entity, is_new = await self._get_saved_show(
            show=show)

        logger.info(f'Entity episode count: {len(entity.episodes)}')

        download_queue = []

        for episode in show.episodes:
            if not entity.contains_episode(
                    episode_id=episode.episode_id):

                logger.info(f'Save episode: {episode.episode_title}')

                if not self.dry_run:
                    audio_data = await self._get_episode_audio(
                        episode=episode)

                    logger.info(f'Bytes fetched: {len(audio_data.content)}')

                downloaded_episode = DownloadedEpisode(
                    episode=episode,
                    show=show,
                    size=len(audio_data.content) if not self.dry_run else 0)

                download_queue.append(downloaded_episode)

                if not self.dry_run:
                    await self._upload_file(
                        episode=downloaded_episode,
                        audio=audio_data.content)

        return (
            download_queue,
            show,
            is_new
        )
