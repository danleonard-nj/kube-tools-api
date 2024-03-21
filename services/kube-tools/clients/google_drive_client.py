from typing import Any

from domain.google import (GoogleClientScope, GoogleDriveDirectory,
                           GoogleDriveFilePermission, GoogleDriveFileUpload)
from framework.clients.cache_client import CacheClientAsync
from framework.logger.providers import get_logger
from googleapiclient.discovery import build
from services.google_auth_service import GoogleAuthService

logger = get_logger(__name__)

GOOGLE_DRIVE_QUERY = "'root' in parents"
GOOGLE_DRIVE_REPORT_FIELDS = "nextPageToken, files(id, name, mimeType, modifiedTime, size)"
CACHE_ENABLED = True


class GoogleDriveClient:
    def __init__(
        self,
        auth_service: GoogleAuthService,
        cache_client: CacheClientAsync
    ):
        self._auth_service = auth_service
        self._cache_client = cache_client
        self._client = None

    async def upload_file(
        self,
        filename: str,
        data: bytes
    ):
        client = await self._get_client()

        logger.info(f'Uploading file: {filename}')
        logger.info(f'File size: {len(data)} bytes')

        upload = GoogleDriveFileUpload(
            filename=filename,
            data=data,
            mimetype='audio/mpeg',
            parent_directory=GoogleDriveDirectory.PodcastDirectoryId)

        file = client.files().create(
            body=upload.metadata,
            media_body=upload.media,
            fields='id').execute()

        permission = GoogleDriveFilePermission()

        result = client.permissions().create(
            fileId=file.get('id'),
            body=permission.to_dict()
        ).execute()

        logger.info(f'Drive file uploaded successfully: {filename}')
        return result

    async def get_drive_file_details(
        self
    ):
        client = await self._get_client()

        # Call the Drive v3 API to fetch the 100 largest files
        results = client.files().list(
            pageSize=100, fields="nextPageToken, files(id, name, size, createdTime, modifiedTime)",
            orderBy="quotaBytesUsed desc").execute()

        return results.get('files', [])

    async def _get_client(
        self
    ) -> Any:
        logger.info('Creating Google Drive client')

        auth_client = await self._auth_service.get_auth_client(
            scopes=GoogleClientScope.Drive)

        client = build(
            'drive',
            'v3',
            credentials=auth_client
        )

        logger.info('Google Drive client created successfully')
        return client
