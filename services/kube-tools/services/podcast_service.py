import asyncio
import io
import random
from typing import Dict, List, Tuple

import feedparser
import httpx
from clients.email_gateway_client import EmailGatewayClient
from clients.google_drive_client_async import (GoogleDriveClientAsync,
                                               GoogleDriveUploadRequest)
from data.podcast_repository import PodcastRepository
from domain.drive import PermissionRole, PermissionType
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
from framework.validators.nulls import none_or_whitespace
from httpx import AsyncClient, Response
from services.event_service import EventService
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024 * 4  # 8MB


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
        http_client: AsyncClient
    ):
        self._configuration = configuration
        self._random_delay = self._configuration.podcasts.get(
            'random_delay')

        self._podcast_repository = podcast_repository
        self._google_drive_client = google_drive_client
        self._email_gateway_client = email_gateway_client
        self._feature_client = feature_client
        self._event_service = event_service
        self._http_client = http_client

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
        downloads, show = await self._sync_feed(
            rss_feed=feed)

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

    async def get_episode_audio(
        self,
        episode: Episode
    ) -> Response:

        ArgumentNullException.if_none(episode, 'episode')

        logger.info(f'Fetching audio for episode: {episode.episode_title}: {episode.audio}')

        response = await self._http_client.get(
            url=episode.audio,
            follow_redirects=True)

        if response.is_error:
            logger.warning(f'Failed to fetch audio: {response.status_code}: {response.text}')
            raise PodcastServiceException(f'Failed to fetch audio: {response.status_code}')

        return response

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
        rss_feed: Feed
    ) -> Tuple[List[DownloadedEpisode], Show]:

        ArgumentNullException.if_none(rss_feed, 'rss_feed')

        await self._wait_random_delay()

        logger.info(f'Fetching RSS feed for show: {rss_feed.name}')

        feed_data = await self._get_feed_request(
            rss_feed=rss_feed)

        logger.info(f'Parsing show from feed data (feedparser)')

        # Parse the RSS feed using feedparser
        parsed_feed = feedparser.parse(feed_data.text)

        show_title = parsed_feed.feed.get('title', rss_feed.name)
        show_id = show_title  # You may want to hash or uuid this

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

        # Use a set for fast episode existence checks (DSA improvement)
        existing_episode_ids = set(ep.episode_id for ep in entity.episodes)
        download_queue = []
        episodes_synced = 0
        # Loop until no new episodes remain or sync cap is reached
        while episodes_synced < 5:
            new_episodes = [ep for ep in show.episodes if ep.episode_id not in existing_episode_ids]
            if not new_episodes:
                break
            episode = new_episodes[0]
            logger.info(f'Save episode: {episode.episode_title}')
            downloaded_episode = DownloadedEpisode(episode=episode, show=show)
            exists = await self._google_drive_client.file_exists(
                directory_id=GoogleDriveDirectory.PodcastDirectoryId,
                filename=downloaded_episode.get_filename())
            if exists:
                logger.info(f'Episode already exists: {downloaded_episode.get_filename()}')
                existing_episode_ids.add(episode.episode_id)
                continue
            await self.upload_file_async(downloaded_episode=downloaded_episode)
            show.episodes.append(episode)
            show.modified_date = DateTimeUtil.timestamp()
            await self._podcast_repository.update(
                selector=show.get_selector(),
                values=show.to_dict())
            download_queue.append(downloaded_episode)
            episodes_synced += 1
            existing_episode_ids.add(episode.episode_id)
        return (download_queue, show)

    async def upload_file_async(
        self,
        downloaded_episode: DownloadedEpisode,
    ) -> None:
        '''
        Upload podcast audio to Google Drive
        '''
        ArgumentNullException.if_none(downloaded_episode, 'episode')

        file_metadata = GoogleDriveUploadRequest(
            name=downloaded_episode.get_filename(),
            parents=[GoogleDriveDirectory.PodcastDirectoryId])

        logger.info(f'Upload metadata: {file_metadata.to_dict()}')

        logger.info(f'Downloading episode audio')
        audio_response = await self.get_episode_audio(episode=downloaded_episode.episode)
        audio_bytes = audio_response.content
        downloaded_episode.size = len(audio_bytes)

        logger.info(f'Downloaded bytes: {downloaded_episode.size}')

        # Validate file size
        MIN_FILE_SIZE = 1024
        if downloaded_episode.size < MIN_FILE_SIZE:
            logger.error(f'Audio file is less than the threshold size to upload: {downloaded_episode.size}')
            raise PodcastServiceException(
                f'Audio file is less than the threshold size to upload: {downloaded_episode.size}')

        await asyncio.sleep(1)  # Wait for session creation if needed

        session_url = await self._google_drive_client.create_resumable_upload_session(
            file_metadata=file_metadata.to_dict())
        logger.info(f'Resumable upload session created')

        try:
            file_id = await self._upload_chunks(session_url, audio_bytes, downloaded_episode.size)
        except Exception as ex:
            logger.error(f'Failed during chunked upload: {ex}')
            raise Exception(f'Failed during chunked upload: {ex}')

        if none_or_whitespace(file_id):
            logger.error(f'No valid file ID returned after upload')
            raise PodcastServiceException('No valid file ID returned from file upload')

        logger.info(f'Creating public permission for file: {file_id}')
        try:
            permission = await self._google_drive_client.create_permission(
                file_id=file_id,
                _type=PermissionType.ANYONE,
                role=PermissionRole.READER,
                value=None)
        except Exception as ex:
            logger.error(f'Failed to create public permission for file {file_id}: {ex}')
            raise Exception(f'Failed to create public permission for file {file_id}: {ex}')

        logger.info(f'Public permission created: {permission}')

    async def _upload_chunks(self, session_url, audio_bytes, total_size):
        start_byte = 0
        upload_response = None
        with io.BytesIO(audio_bytes) as buffer:
            while True:
                percent_complete = round(start_byte / total_size * 100, 2) if total_size else 0
                logger.info(f'Percent complete: {percent_complete}%')
                chunk = buffer.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    logger.info(f'End of buffer reached')
                    break
                try:
                    upload_response = await self._google_drive_client.upload_file_chunk(
                        session_url=session_url,
                        chunk=chunk,
                        start_byte=start_byte,
                        total_size=total_size)
                except Exception as ex:
                    logger.error(f'Chunk upload failed at byte {start_byte}: {ex}')
                    raise Exception(f'Chunk upload failed at byte {start_byte}: {ex}')
                if upload_response is None:
                    logger.error('No response from upload_file_chunk')
                    raise PodcastServiceException('No response from upload_file_chunk')
                if upload_response.status_code not in [200, 201, 308]:
                    logger.error(f'Chunk upload failed: {upload_response.status_code} {upload_response.text}')
                    raise PodcastServiceException(f'Chunk upload failed: {upload_response.status_code}')
                start_byte += len(chunk)
                if upload_response.status_code in [200, 201]:
                    logger.info(f'Chunk upload successful')
                    break
        if upload_response is None:
            logger.error(f'Invalid response on file upload completion')
            raise PodcastServiceException('Invalid response on file upload completion')
        try:
            file_id = upload_response.json().get('id')
        except Exception as ex:
            logger.error(f'Failed to parse file ID from upload response: {ex}')
            raise PodcastServiceException('No valid file ID returned from file upload')
        return file_id
