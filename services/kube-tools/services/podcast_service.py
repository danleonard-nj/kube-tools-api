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
from models.podcast_config import PodcastConfig
from services.event_service import EventService
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)

UPLOAD_CHUNK_SIZE = 1024 * 1024 * 4  # 8MB
MAX_EPISODE_DOWNLOADS = 10


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

        # await self._event_service.dispatch_email_event(
        #     endpoint=endpoint,
        #     message=email_request.to_dict())

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
        # Start with the DB entity's episodes list
        db_episodes = list(entity.episodes)
        db_episode_ids = set(ep.episode_id for ep in db_episodes)
        to_add = []  # Episodes to add to DB (uploaded or found in Drive)
        download_queue = []
        if folder_name:
            drive_folder_id = await self._resolve_drive_folder_id(folder_name)
        else:
            drive_folder_id = GoogleDriveDirectory.PodcastDirectoryId

        # Find up to MAX_EPISODE_DOWNLOADS new episodes to process
        new_episodes = [ep for ep in show.episodes if ep.episode_id not in db_episode_ids][:MAX_EPISODE_DOWNLOADS]
        if not new_episodes:
            return ([], show)

        for episode in new_episodes:
            downloaded_episode = DownloadedEpisode(episode=episode, show=show)
            exists = await self._google_drive_client.file_exists(
                directory_id=drive_folder_id,
                filename=downloaded_episode.get_filename())
            if exists:
                to_add.append(episode)
            else:
                try:
                    await self.upload_file_async(downloaded_episode=downloaded_episode, drive_folder_path=folder_name)
                    to_add.append(episode)
                    download_queue.append(downloaded_episode)
                except Exception as ex:
                    logger.error(f'Upload failed for episode: {episode.episode_title} - {ex}')

        # Deduplicate and update DB ONCE
        all_episodes = db_episodes + [ep for ep in to_add if ep.episode_id not in db_episode_ids]
        show.episodes = all_episodes
        show.modified_date = DateTimeUtil.timestamp()
        await self._podcast_repository.update(
            selector=show.get_selector(),
            values=show.to_dict())

        return (download_queue, show)

    async def _resolve_drive_folder_id(self, folder_path: str) -> str:
        """
        Given a folder path like 'Podcasts/CBB', resolve and create (if needed) the folder structure in Google Drive and return the final folder's ID.
        """
        if not folder_path or folder_path.strip() == "":
            return GoogleDriveDirectory.PodcastDirectoryId

        # Split path and start from root Podcasts folder
        parts = folder_path.strip("/\\").split("/")
        parent_id = GoogleDriveDirectory.PodcastDirectoryId
        for part in parts:
            # Check if folder exists under parent_id
            headers = await self._google_drive_client._get_auth_headers()
            query = {
                'q': f"'{parent_id}' in parents and name = '{part}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                'fields': 'files(id, name)',
                'pageSize': 1
            }
            resp = await self._google_drive_client._http_client.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=headers,
                params=query
            )
            if resp.status_code != 200:
                logger.error(f"Failed to check existence of folder '{part}': {resp.status_code} {resp.text}")
                raise PodcastServiceException(f"Failed to check existence of folder '{part}': {resp.status_code} {resp.text}")
            files = resp.json().get('files', [])
            if files:
                parent_id = files[0]['id']
            else:
                # Create the folder
                folder_metadata = {
                    'name': part,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [parent_id]
                }
                create_resp = await self._google_drive_client._http_client.post(
                    "https://www.googleapis.com/drive/v3/files",
                    headers=headers,
                    json=folder_metadata
                )
                if create_resp.status_code not in [200, 201]:
                    logger.error(f"Failed to create folder '{part}': {create_resp.status_code} {create_resp.text}")
                    raise PodcastServiceException(f"Failed to create folder '{part}': {create_resp.status_code} {create_resp.text}")
                create_json = create_resp.json()
                if 'id' not in create_json:
                    logger.error(f"No 'id' in folder creation response for '{part}': {create_json}")
                    raise PodcastServiceException(f"No 'id' in folder creation response for '{part}': {create_json}")
                parent_id = create_json['id']
        return parent_id

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
            parent_id = await self._resolve_drive_folder_id(drive_folder_path)
        else:
            parent_id = GoogleDriveDirectory.PodcastDirectoryId
        file_metadata = GoogleDriveUploadRequest(
            name=downloaded_episode.get_filename(),
            parents=[parent_id])

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

        # Retry logic for authentication failures
        max_retries = 3
        retry_count = 0
        session_url = None

        while retry_count < max_retries:
            try:
                session_url = await self._google_drive_client.create_resumable_upload_session(
                    file_metadata=file_metadata.to_dict())

                if isinstance(session_url, str) and not none_or_whitespace(session_url):
                    logger.info(f'Resumable upload session created successfully')
                    break
                else:
                    logger.warning(f'Invalid session_url returned: {session_url}')

            except Exception as ex:
                retry_count += 1
                logger.warning(f'Failed to create upload session (attempt {retry_count}/{max_retries}): {ex}')

                if retry_count < max_retries:
                    # Wait before retrying with exponential backoff
                    wait_time = 2 ** retry_count
                    logger.info(f'Waiting {wait_time} seconds before retry...')
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f'All {max_retries} attempts to create upload session failed')
                    raise PodcastServiceException(f'Failed to create resumable upload session after {max_retries} attempts: {str(ex)}')

        if not isinstance(session_url, str) or none_or_whitespace(session_url):
            logger.error(f'Failed to create valid session URL after all retries')
            raise PodcastServiceException('Failed to create a valid resumable upload session')
        try:
            file_id = await self._upload_chunks(session_url, audio_bytes, downloaded_episode.size)
        except Exception as ex:
            logger.error(f'Failed during chunked upload: {ex}')
            raise Exception(f'Failed during chunked upload: {ex}')

        if none_or_whitespace(file_id):
            logger.error(f'No valid file ID returned after upload')
            raise PodcastServiceException('No valid file ID returned from file upload')

        logger.info(f'Creating public permission for file: {file_id}')

        # Retry logic for permission creation (can also fail due to auth issues)
        max_retries = 3
        retry_count = 0
        permission = None

        while retry_count < max_retries:
            try:
                permission = await self._google_drive_client.create_permission(
                    file_id=file_id,
                    _type=PermissionType.ANYONE,
                    role=PermissionRole.READER,
                    value=PermissionType.ANYONE)
                logger.info(f'Public permission created successfully')
                break

            except Exception as ex:
                retry_count += 1
                logger.warning(f'Failed to create permission (attempt {retry_count}/{max_retries}): {ex}')

                if retry_count < max_retries:
                    # Wait before retrying with exponential backoff
                    wait_time = 2 ** retry_count
                    logger.info(f'Waiting {wait_time} seconds before retry...')
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f'All {max_retries} attempts to create permission failed')
                    raise Exception(f'Failed to create public permission for file {file_id} after {max_retries} attempts: {str(ex)}')

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
