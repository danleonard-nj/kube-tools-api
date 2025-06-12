import asyncio
from hashlib import md5
import random
from typing import Dict, List, Tuple
import uuid

import feedparser
import httpx
from clients.email_gateway_client import EmailGatewayClient
from clients.google_drive_client_async import (GoogleDriveClientAsync)
from data.podcast_repository import PodcastRepository
from domain.drive import GoogleDriveUploadRequest
from domain.exceptions import PodcastConfigurationException
from domain.features import Feature
from domain.google import GoogleDriveDirectory
from domain.podcasts.handlers import (AcastFeedHandler, FeedHandler,
                                      GenericFeedHandler)
from domain.podcasts.podcasts import DownloadedEpisode, Episode, Feed, Show
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from httpx import AsyncClient
from models.podcast_config import PodcastConfig
from services.event_service import EventService
from services.google_drive_upload_helper import GoogleDriveUploadHelper
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024 * 4  # 8MB
MAX_EPISODE_DOWNLOADS = 3


class PodcastServiceException(Exception):
    pass


class PodcastService:
    def __init__(
        self,
        podcast_repository: PodcastRepository,
        google_drive_client: GoogleDriveClientAsync,
        email_gateway_client: EmailGatewayClient,
        event_service: EventService,
        feature_client: FeatureClientAsync,
        configuration: Configuration,
        http_client: AsyncClient,
        podcast_config: PodcastConfig
    ):
        self._configuration = configuration
        self._random_delay = podcast_config.random_delay
        self._rss_feeds = podcast_config.feeds

        self._podcast_repository = podcast_repository
        self._google_drive_client = google_drive_client
        self._email_gateway_client = email_gateway_client
        self._feature_client = feature_client
        self._event_service = event_service
        self._http_client = http_client
        self._google_drive_upload_helper = GoogleDriveUploadHelper(google_drive_client)

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

        for feed, folder_name in feeds:
            logger.info(f'Handling feed: {feed.name}')
            try:
                res = await self.handle_feed(
                    feed=feed,
                    folder_name=folder_name)

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
        feed: Feed,
        folder_name: str | None = None
    ):
        ArgumentNullException.if_none(feed, 'feed')

        logger.info(f'Handling RSS feed: {feed.name}')

        # Get episodes to download and show model
        downloads, show = await self._sync_feed(
            rss_feed=feed,
            folder_name=folder_name)

        if not any(downloads):
            logger.info(f'No new episodes for show')
            return

        # Update the show modified date
        show.modified_date = DateTimeUtil.timestamp()

        # Update the show with new episodes
        await self._podcast_repository.update(
            selector=show.get_selector(),
            values=show.to_dict())

        # Send an email for the downloaded episodes
        await self._send_email(
            episodes=downloads)

        return downloads

    def get_feeds(
        self
    ) -> List[tuple[Feed, str | None]]:
        '''
        Get all configured RSS feeds, returning (Feed, folder_name) tuples
        '''
        feeds = []
        for x in self._rss_feeds:
            feed = Feed(x)
            folder_name = x.folder_name
            feeds.append((feed, folder_name))
        return feeds

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

        # Actually send the email event
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

    def get_episode_audio(
        self,
        episode: Episode
    ):
        ArgumentNullException.if_none(episode, 'episode')
        logger.info(f'Fetching audio for episode: {episode.episode_title}: {episode.audio}')
        logger.info(f'Preparing to stream audio from URL: {episode.audio}')
        logger.info(f'HTTP client: {self._http_client}')
        return self._http_client.stream(
            method='GET',
            url=episode.audio,
            follow_redirects=True
        )

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

        if entity is not None:
            return (Show.from_entity(entity), False)

        logger.info(f'Initial insert for show: {show.show_title}')

        show = Show(
            show_id=show.show_id,
            show_title=show.show_title,
            episodes=list())

        result = await self._podcast_repository.insert(
            document=show.to_dict())

        logger.info(f'Insert result: {result.inserted_id}')

        return (show, True)

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
        rss_feed: Feed,
        folder_name: str | None = None
    ) -> Tuple[List[DownloadedEpisode], Show]:

        ArgumentNullException.if_none(rss_feed, 'rss_feed')

        await self._wait_random_delay()

        logger.info(f'Fetching RSS feed for show: {rss_feed.name}')

        feed_data = await self._get_feed_request(
            rss_feed=rss_feed)

        logger.info(f'Parsing show from feed data (feedparser)')

        # Parse the RSS feed using feedparser
        parsed_feed = feedparser.parse(feed_data.text)

        show_id = str(uuid.uuid4())
        if 'acast_showid' in parsed_feed.feed:
            show_id = parsed_feed.feed['acast_showid']
        elif 'id' in parsed_feed.feed:
            show_id = parsed_feed.feed['id']
        elif 'link' in parsed_feed.feed:
            hashed = uuid.UUID(md5(show_id.encode('utf-8')).hexdigest())
            show_id = str(hashed)

        show_title = parsed_feed.feed.get('title', rss_feed.name)
        # show_id = show_title  # You may want to hash or uuid this

        episodes = []
        for entry in parsed_feed.entries:
            episode_id = entry.get('guid') or entry.get('id') or entry.get('link')
            episode_title = entry.get('title')
            audio_url = None
            if 'enclosures' in entry and entry['enclosures']:
                audio_url = entry['enclosures'][0].get('href')
            elif 'links' in entry:
                for link in entry['links']:
                    if link.get('type', '').startswith('audio'):
                        audio_url = link.get('href')
                        break

            if not (episode_id and episode_title and audio_url):
                continue

            episode = Episode(
                episode_id=episode_id,
                episode_title=episode_title,
                audio=audio_url
            )

            episodes.append(episode)

        show = Show(
            show_id=show_id,
            show_title=show_title,
            episodes=episodes
        )

        logger.info(f'Feed episode count: {len(show.episodes)}')

        # Get the stored show
        entity, is_new = await self._get_saved_show(
            show=show)

        logger.info(f'Entity episode count: {len(entity.episodes)}')

        # Use a set for fast episode existence checks
        # Start with the DB entity's episodes list
        db_episodes = list(entity.episodes)
        db_episode_ids = set(ep.episode_id for ep in db_episodes)
        to_add = []  # Episodes to add to DB (uploaded or found in Drive)
        download_queue = []
        if folder_name:
            drive_folder_id = await self._google_drive_client.resolve_drive_folder_id(folder_name)
        else:
            drive_folder_id = GoogleDriveDirectory.PodcastDirectoryId

        # Find up to MAX_EPISODE_DOWNLOADS new episodes to process
        new_episodes = [ep for ep in show.episodes if ep.episode_id not in db_episode_ids][:MAX_EPISODE_DOWNLOADS]
        if not new_episodes:
            return ([], show)

        # Concurrency control for uploads
        max_concurrent_uploads = 6
        semaphore = asyncio.Semaphore(max_concurrent_uploads)
        upload_tasks = []

        async def upload_with_semaphore(downloaded_episode, folder_name):
            async with semaphore:
                try:
                    await self.upload_file_async(downloaded_episode=downloaded_episode, drive_folder_path=folder_name)
                    to_add.append(downloaded_episode.episode)
                    download_queue.append(downloaded_episode)
                except Exception as ex:
                    logger.error(f'Upload failed for episode: {downloaded_episode.episode.episode_title} - {ex}')

        for episode in new_episodes:
            downloaded_episode = DownloadedEpisode(episode=episode, show=show)
            exists = await self._google_drive_client.file_exists(
                directory_id=drive_folder_id,
                filename=downloaded_episode.get_filename())
            if exists:
                to_add.append(episode)
            else:
                upload_tasks.append(upload_with_semaphore(downloaded_episode, folder_name))

        if upload_tasks:
            await asyncio.gather(*upload_tasks)

        # Deduplicate and update DB ONCE
        all_episodes = db_episodes + [ep for ep in to_add if ep.episode_id not in db_episode_ids]
        show.episodes = all_episodes
        show.modified_date = DateTimeUtil.timestamp()
        await self._podcast_repository.update(
            selector=show.get_selector(),
            values=show.to_dict())

        return (download_queue, show)

    async def upload_file_async(
        self,
        downloaded_episode: DownloadedEpisode,
        drive_folder_path: str = None
    ) -> None:
        '''
        Upload podcast audio to Google Drive
        '''
        ArgumentNullException.if_none(downloaded_episode, 'episode')

        # Use the provided drive_folder_path if given, else default to root
        if drive_folder_path:
            logger.info(f'Resolving Google Drive folder ID for path: {drive_folder_path}')
            parent_id = await self._google_drive_client.resolve_drive_folder_id(drive_folder_path)
            logger.info(f'Resolved folder ID: {parent_id}')
        else:
            logger.info('No drive_folder_path provided, using default PodcastDirectoryId')
            parent_id = GoogleDriveDirectory.PodcastDirectoryId
        file_metadata = GoogleDriveUploadRequest(
            name=downloaded_episode.get_filename(),
            parents=[parent_id])

        # Use the new helper method for download+upload
        await self._google_drive_upload_helper.upload_episode(
            episode=downloaded_episode.episode,
            show=downloaded_episode.show,
            file_metadata=file_metadata,
            get_episode_audio_fn=self.get_episode_audio
        )
