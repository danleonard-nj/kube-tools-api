from typing import Any

from domain.google import GoogleDriveDirectory, GoogleDriveFileUpload
from framework.logger.providers import get_logger
from googleapiclient.discovery import build
from services.google_auth_service import GoogleAuthService

logger = get_logger(__name__)


class GoogleDriveClient:
    def __init__(
        self,
        auth_service: GoogleAuthService
    ):
        self.__auth_service = auth_service

    async def __get_creds(self):
        client = await self.__auth_service.get_client_by_name(
            client_name='kube-tools')

        return client.get_google_creds()

    async def __get_client(
        self
    ) -> Any:
        logger.info('Creating Google Drive client')

        credentials = await self.__get_creds()
        client = build('drive', 'v3', credentials=credentials)
        logger.info('Google Drive client created successfully')

        return client

    async def upload_file(self, filename: str, data: bytes):
        client = await self.__get_client()

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

        permission = {
            'type': 'anyone',
            'value': 'anyone',
            'role': 'reader'
        }

        return client.permissions().create(
            fileId=file.get('id'),
            body=permission).execute()
