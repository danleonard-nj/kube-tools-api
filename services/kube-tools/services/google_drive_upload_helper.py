import asyncio
from framework.logger.providers import get_logger
from framework.validators.nulls import none_or_whitespace
from domain.drive import PermissionRole, PermissionType

logger = get_logger(__name__)


class GoogleDriveUploadHelper:
    def __init__(self, google_drive_client):
        self._google_drive_client = google_drive_client

    async def upload_file(
        self,
        file_metadata,
        audio_stream,
        file_size,
        min_file_size=1024,
        chunk_size=1024 * 1024 * 4
    ):
        session_url = await GoogleDriveUploadHelper._retry(
            self._google_drive_client.create_resumable_upload_session,
            file_metadata=file_metadata.to_dict()
        )

        start_byte = 0
        total_uploaded = 0
        upload_response = None

        async for chunk in audio_stream.aiter_bytes(chunk_size):
            if not chunk:
                break
            upload_response = await self._google_drive_client.upload_file_chunk(
                session_url=session_url,
                chunk=chunk,
                start_byte=start_byte,
                total_size=file_size
            )
            start_byte += len(chunk)
            total_uploaded += len(chunk)
            if file_size:
                percent = (total_uploaded / file_size) * 100
                logger.info(f'Upload progress: {percent:.2f}% ({total_uploaded}/{file_size} bytes)')
            if upload_response.status_code in [200, 201]:
                break
            if upload_response.status_code not in [200, 201, 308]:
                raise Exception(f'Chunk upload failed: {upload_response.status_code}')

        file_id = upload_response.json().get('id')
        if none_or_whitespace(file_id):
            raise Exception('No valid file ID returned from file upload')

        if file_size is None:
            file_size = total_uploaded
        if file_size < min_file_size:
            raise Exception(f'Audio file is less than the threshold size to upload: {file_size}')

        await GoogleDriveUploadHelper._retry(
            self._google_drive_client.create_permission,
            file_id=file_id,
            _type=PermissionType.ANYONE,
            role=PermissionRole.READER,
            value=PermissionType.ANYONE
        )

        return file_id

    async def upload_episode(
        self,
        episode,
        show,
        file_metadata,
        get_episode_audio_fn,
        min_file_size=1024,
        chunk_size=1024 * 1024 * 4
    ):
        """
        Handles downloading the episode audio and uploading it to Google Drive.
        - episode: the Episode object
        - show: the Show object
        - file_metadata: GoogleDriveUploadRequest
        - get_episode_audio_fn: function to get the audio stream (should be async context manager)
        """
        async with get_episode_audio_fn(episode=episode) as audio_response:
            content_length = audio_response.headers.get('content-length')
            size = int(content_length) if content_length else None
            file_id = await self.upload_file(
                file_metadata=file_metadata,
                audio_stream=audio_response,
                file_size=size,
                min_file_size=min_file_size,
                chunk_size=chunk_size
            )
            return file_id

    @staticmethod
    async def _retry(func, *args, max_retries=3, **kwargs):
        for attempt in range(1, max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as ex:
                if attempt == max_retries:
                    raise
                wait_time = 2 ** attempt
                logger.warning(f'Attempt {attempt} failed: {ex}. Retrying in {wait_time}s...')
                await asyncio.sleep(wait_time)
