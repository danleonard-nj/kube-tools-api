import asyncio
import io
import random
from typing import Dict, List, Tuple

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

                downloaded_episode = DownloadedEpisode(
                    episode=episode,
                    show=show)

                # Check if the episode already exists in Google Drive
                exists = await self._google_drive_client.file_exists(
                    directory_id=GoogleDriveDirectory.PodcastDirectoryId,
                    filename=downloaded_episode.get_filename())

                if exists:
                    logger.info(f'Episode already exists: {downloaded_episode.get_filename()}')
                    continue

                await self.upload_file_async(
                    downloaded_episode=downloaded_episode)

                download_queue.append(downloaded_episode)

        return (
            download_queue,
            show
        )

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
        downloaded_episode.size = len(audio_response.content)

        logger.info(f'Downloaded bytes: {len(audio_response.content)}')

        # Throw if the audio file is less than 1KB - occasionally the
        # response is an error message but we get a 200 status anyway
        if len(audio_response.content) < 1024:
            raise PodcastServiceException(
                f'Audio file is less than the threshold size to upload: {audio_response}')

        # Wait for the session to be created
        await asyncio.sleep(1)

        logger.info(f'Getting buffer for episode')
        with io.BytesIO(audio_response.content) as buffer:

            # Create a resumable upload session for the file
            logger.info(f'Creating resumable upload session')
            session_url = await self._google_drive_client.create_resumable_upload_session(
                file_metadata=file_metadata.to_dict())

            buffer.seek(0)

            start_byte = 0
            upload_response = None
            total_size = downloaded_episode.size
            while True:
                percent_complete = round(start_byte / total_size * 100, 2) if total_size else 0
                logger.info(f'Percent complete: {percent_complete}%')

                chunk = buffer.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    logger.info(f'End of buffer reached')
                    break

                upload_response = await self._google_drive_client.upload_file_chunk(
                    session_url=session_url,
                    chunk=chunk,
                    start_byte=start_byte,
                    total_size=total_size)

                if upload_response is None:
                    logger.error('No response from upload_file_chunk')
                    raise PodcastServiceException('No response from upload_file_chunk')

                if upload_response.status_code not in [200, 201, 308]:
                    logger.error(f'Chunk upload failed: {upload_response.status_code} {upload_response.text}')
                    raise PodcastServiceException(f'Chunk upload failed: {upload_response.status_code}')

                start_byte += len(chunk)

                # 308 = Resume Incomplete, 200/201 = Success
                if upload_response.status_code in [200, 201]:
                    logger.info(f'Chunk upload successful')
                    break

        if upload_response is None:
            logger.info(f'Invalid response on file upload completion')
            raise PodcastServiceException('Invalid response on file upload completion')

        try:
            file_id = upload_response.json().get('id')
        except Exception as ex:
            logger.error(f'Failed to parse file ID from upload response: {ex}')
            raise PodcastServiceException('No valid file ID returned from file upload')

        if none_or_whitespace(file_id):
            logger.info(f'No valid file ID returned')
            raise PodcastServiceException('No valid file ID returned from file upload')

        logger.info(f'Creating public permission for file: {file_id}')
        permission = await self._google_drive_client.create_permission(
            file_id=file_id,
            permission_type=PermissionType.ANYONE,
            role=PermissionRole.READER,
            value=PermissionType.ANYONE)

        logger.info(f'Public permission created: {permission}')
