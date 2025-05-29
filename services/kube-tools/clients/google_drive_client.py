from typing import Any

from domain.google import (GoogleClientScope, GoogleDriveFilePermission,
                           GoogleDriveFileUpload)
from framework.logger.providers import get_logger
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from services.google_auth_service import GoogleAuthService

logger = get_logger(__name__)


class GoogleDriveClient:
    def __init__(
        self,
        auth_service: GoogleAuthService
    ):
        self._auth_service = auth_service
        self._client = None

    async def upload_file(
        self,
        filename: str,
        data: bytes,
        parent_directory: str = None
    ):
        client = await self._get_client()

        logger.info(f'Uploading file: {filename}')
        logger.info(f'File size: {len(data)} bytes')

        upload = GoogleDriveFileUpload(
            filename=filename,
            data=data,
            mimetype='audio/mpeg',
            parent_directory=parent_directory)

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

    async def file_exists(
        self,
        directory_id: str,
        filename: str
    ):
        client = await self._get_client()

        logger.info(f'Checking if file exists: {filename} in directory: {directory_id}')
        query = f"name='{filename}' and trashed=false and '{directory_id}' in parents"
        # query = f"name='{filename}' and trashed=false"

        results = client.files().list(q=query, spaces='drive',
                                      fields='files(id, name)').execute()

        items = results.get('files', [])

        exists = len(items) > 0
        logger.info(f'File exists: {filename}: {directory_id}: {exists}')

        return exists

    async def _get_client(
        self
    ) -> Any:
        logger.info('Creating Google Drive client')

        # Get token and create credentials manually
        token = await self._auth_service.get_token(
            client_name='drive-client',
            scopes=[GoogleClientScope.Drive])

        # Create a temporary credentials object for the Google API client
        creds = Credentials(token=token)

        client = build(
            'drive',
            'v3',
            credentials=creds
        )

        logger.info('Google Drive client created successfully')
        return client
