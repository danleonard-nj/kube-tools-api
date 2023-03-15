from typing import Any

from framework.logger.providers import get_logger
from googleapiclient.discovery import build

from domain.google import (GoogleClientScope, GoogleDriveDirectory,
                           GoogleDriveFilePermission, GoogleDriveFileUpload)
from services.google_auth_service import GoogleAuthService

logger = get_logger(__name__)


class GoogleDriveClient:
    def __init__(
        self,
        auth_service: GoogleAuthService
    ):
        self.__auth_service = auth_service

    async def upload_file(
        self,
        filename: str,
        data: bytes
    ):
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

        permission = GoogleDriveFilePermission()

        result = client.permissions().create(
            fileId=file.get('id'),
            body=permission.to_dict()
        ).execute()

        logger.info(f'Drive file uploaded successfully: {filename}')
        return result

    async def __get_client(
        self
    ) -> Any:
        logger.info('Creating Google Drive client')

        auth_client = await self.__auth_service.get_auth_client(
            scopes=GoogleClientScope.Drive)

        client = build(
            'drive',
            'v3',
            credentials=auth_client
        )

        logger.info('Google Drive client created successfully')
        return client
