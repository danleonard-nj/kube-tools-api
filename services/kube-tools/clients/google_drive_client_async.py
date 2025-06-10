import logging
import os
from datetime import datetime

import aiofiles
import httpx
from domain.drive import (GoogleDriveFileDetailsRequest,
                          GoogleDriveFileExistsRequest,
                          GoogleDrivePermissionRequest,
                          GoogleDriveUploadRequest, PermissionRole,
                          PermissionType)
from domain.google import GoogleClientScope
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace
from httpx import AsyncClient
from services.google_auth_service import GoogleAuthService
from tenacity import (RetryError, after_log, before_log, before_sleep_log,
                      retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

logger = get_logger(__name__)

CHUNK_SIZE = 256 * 1024  # 256 KB


class GoogleDriveClientAsyncException(Exception):
    pass


class GoogleDriveClientAsync:
    def __init__(
        self,
        http_client: AsyncClient,
        auth_service: GoogleAuthService
    ):
        self._http_client = http_client
        self._auth_service = auth_service

    async def _get_auth_headers(
        self
    ):
        """
        Retrieves the authorization headers for making requests to the Google Drive API.

        Returns:
            dict: The authorization headers with the access token.
        """
        token = await self._auth_service.get_token(
            client_name='drive-client',
            scopes=[GoogleClientScope.Drive])

        return {
            'Authorization': f'Bearer {token}'
        }

    async def create_resumable_upload_session(
        self,
        file_metadata: dict
    ):
        """
        Creates a resumable upload session for the given file metadata.

        Args:
            file_metadata (dict): The metadata of the file to be uploaded.

        Returns:
            str: The URL of the resumable upload session.

        """

        logger.info(f'Creating resumable session for file: {file_metadata.get("name")}')
        try:
            headers = await self._get_auth_headers() | {
                "Content-Type": "application/json; charset=UTF-8"
            }
        except Exception as ex:
            logger.error(f'Failed to get auth headers for resumable upload: {ex}')
            raise
        logger.info(f'Resumable session headers: {headers}')
        try:
            response = await self._http_client.post(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
                headers=headers,
                json=file_metadata)
        except Exception as ex:
            logger.error(f'HTTP request to create resumable session failed: {ex}')
            raise
        logger.info(f'Resumable session response: {response.status_code} {response.text}')
        if response.status_code != 200:
            logger.error(f'Failed to create resumable session. Status: {response.status_code}, Body: {response.text}')
        session_url = response.headers.get('Location')
        if not session_url:
            logger.error(f'No Location header found in resumable session response. Headers: {response.headers}')
        logger.info(f'Resumable session location: {session_url}')

        return session_url

    async def _cancel_resumable_session(
        self,
        session_url: str
    ) -> dict:
        """
        Cancels a resumable session.

        Args:
            session_url (str): The URL of the resumable session to cancel.

        Returns:
            The response from the HTTP DELETE request.
        """

        logger.info(f'Cancelling resumable session: {session_url}')

        response = await self._http_client.delete(session_url)
        return response.json()

    def _get_chunk_headers(
        self,
        start_byte: int,
        end_byte: int,
        total_size: int
    ):
        """
        Generate the headers for a chunked upload request.

        Args:
            token (str): The access token for authorization.
            start_byte (int): The starting byte of the chunk.
            end_byte (int): The ending byte of the chunk.
            total_size (int): The total size of the file being uploaded.

        Returns:
            dict: The headers for the chunked upload request.
        """

        return {
            "Content-Range": f"bytes {start_byte}-{end_byte}/{total_size}",
            "Content-Length": str(end_byte - start_byte + 1)
        }

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        before=before_log(logger, logging.INFO),
        after=after_log(logger, logging.INFO),
        before_sleep=before_sleep_log(logger, logging.INFO))
    async def upload_file_chunk(
        self,
        session_url: str,
        total_size: int,
        start_byte: int,
        chunk: bytes
    ):
        """
        Uploads a chunk of a file to the specified session URL.

        Args:
            session_url (str): The URL of the upload session.
            total_size (int): The total size of the file being uploaded.
            start_byte (int): The starting byte position of the chunk.
            chunk (bytes): The chunk of the file to be uploaded.

        Returns:
            The response from the HTTP client after uploading the chunk.
        """

        try:
            logger.info(f"Uploading session '{session_url}' chunk starting at byte: {start_byte}")

            auth_headers = await self._get_auth_headers()

            # Generate headers for the chunk
            headers = auth_headers | self._get_chunk_headers(
                start_byte=start_byte,
                end_byte=start_byte + len(chunk) - 1,
                total_size=total_size)

            logger.info(f'Chunk headers: {headers}')

            response = await self._http_client.put(
                session_url,
                headers=headers,
                content=chunk)

            logger.info(response.text)

            return response

        except RetryError as e:
            # Cancel the session if an error occurs and we've retried too many times
            logger.info(f"Failed to upload chunk starting at byte {start_byte}")
            await self._cancel_resumable_session(session_url)
            raise GoogleDriveClientAsyncException(f"Resumable upload failed: {str(e)}")

        except httpx.HTTPStatusError as ex:
            if ex.status_code == 308:
                logger.info('Ignoring 308')
                logger.info(f'Uploaded chunk')
                pass
            logger.error(f"Failed to upload chunk starting at byte {start_byte}. Error: {str(ex)}")

    async def upload_large_file(
        self,
        filename: str,
        filepath: str,
        parent_directory: str = None,
        anyone_permission: bool = True
    ):
        """
        Uploads a large file to Google Drive using a resumable upload session.

        Args:
            filename (str): The name of the file to be uploaded.
            filepath (str): The path to the file on the local system.
            parent_directory (str, optional): The ID of the parent directory in Google Drive. Defaults to None.

        Returns:
            None
        """

        file_exists = os.path.exists(filepath)

        if not file_exists:
            logger.info(f'File does not exist: {filepath}')
            raise GoogleDriveClientAsyncException(f'File does not exist: {filepath}')

        file_size = os.path.getsize(filepath)

        file_metadata = GoogleDriveUploadRequest(
            name=filename,
            parents=[parent_directory] if parent_directory else None)

        logger.info(f'Creating resumable session for large file: {filename}')
        session_url = await self.create_resumable_upload_session(
            file_metadata.to_dict())

        if none_or_whitespace(session_url):
            logger.info(f'Failed to create resumable session for file: {filename}')
            raise GoogleDriveClientAsyncException(f'Failed to create resumable session for file: {filename}')

        logger.info(f'Resumable session URL: {session_url}')

        logger.info(f'Getting file handle for large file: {filename}')
        async with aiofiles.open(filepath, 'rb') as f:

            logger.info(f'File handle opened successfully')

            upload_start = datetime.now()
            start_byte = 0

            while start_byte < file_size:
                logger.info(f'Percent complete: {start_byte / file_size * 100}%')

                try:
                    chunk = await f.read(CHUNK_SIZE)

                    response = await self.upload_file_chunk(
                        session_url,
                        file_size,
                        start_byte,
                        chunk)

                    logger.info(f'Chunk upload response: {response.status_code}')

                    start_byte += len(chunk)

                except RetryError:
                    print(f"Failed to upload chunk starting at byte {start_byte}. Canceling upload session.")
                    await self._cancel_resumable_session(session_url)
                    return

                except Exception as e:
                    print(f"Failed to upload chunk starting at byte {start_byte}. Error: {e}: Retrying")
                    return

                # Check if the response is successful before continuing to the next chunk
                if response.status_code in (200, 201):
                    logger.info(f"File uploaded successfully")
                    break

            upload_end = datetime.now()
            upload_duration = upload_end - upload_start
            logger.info(f"Upload duration: {upload_duration}")

            file_id = response.json().get('id')
            logger.info(f'Created file ID: {file_id}')

            if anyone_permission:
                logger.info(f'Creating file permission')
                permission = await self.create_permission(
                    file_id=file_id,
                    _type=PermissionType.ANYONE,
                    role=PermissionRole.READER,
                    value=PermissionType.ANYONE)

                logger.info(f'Created permission: {permission}')

            return response.json()

    async def upload_single(
        self,
        filename: str,
        filepath: str,
        parent_directory: str = None
    ):
        """
        Uploads a single file to Google Drive.

        Args:
            filename (str): The name of the file to be uploaded.
            filepath (str): The path to the file on the local system.
            parent_directory (str, optional): The ID of the parent directory in Google Drive. Defaults to None.

        Returns:
            dict: The JSON response from the upload request.

        Raises:
            Any exceptions that may occur during the upload process.
        """

        logger.info(f'Uploading single file: {filename}')

        req = GoogleDriveUploadRequest(
            name=filename,
            parents=[parent_directory] if parent_directory else None)

        logger.info(f'Upload request: {req.to_dict()}')

        async with aiofiles.open(filepath, 'rb') as file:
            data = await file.read()

            headers = await self._get_auth_headers() | {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(len(data)),
            }

            response = await self._http_client.post(
                "https://www.googleapis.com/upload/drive/v3/files",
                headers=headers,
                params=req.to_dict(),
                content=data)

            logger.info(f'Upload response: {response.status_code}')

            return response.json()

    async def create_permission(
        self,
        file_id: str,
        _type: str,
        role: str,
        value: str
    ):
        """
        Creates a permission for a file in Google Drive.

        Args:
            file_id (str): The ID of the file to create the permission for.
            email (str): The email address of the user to grant the permission to.
            role (str): The role to assign to the user.

        Returns:
            dict: The JSON response from the API containing information about the created permission.
        """

        logger.info(f'Creating permission for file: {file_id} with value: {value} and role: {role}')

        headers = await self._get_auth_headers()

        req = GoogleDrivePermissionRequest(
            role=role,
            _type=_type,
            value=value)

        logger.info(f'Permission request: {req.to_dict()}')

        response = await self._http_client.post(
            f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
            headers=headers,
            json=req.to_dict())

        logger.info(f'Create permission response: {response.status_code}')

        return response.json()

    async def get_drive_file_details(
        self,
        max_results=250
    ):
        """
        Fetches drive file details from Google Drive API.

        Args:
            max_results (int): The maximum number of file details to fetch. Defaults to 250.

        Returns:
            list: A list of file details.

        """
        logger.info(f'Fetching drive file details')

        headers = await self._get_auth_headers()
        all_files = []
        next_page_token = None

        while True:
            req = GoogleDriveFileDetailsRequest(
                page_size=100,
                page_token=next_page_token)

            response = await self._http_client.get(
                "https://www.googleapis.com/drive/v3/files",
                params=req.to_dict(),
                headers=headers
            )

            results = response.json()
            files = results.get('files', [])
            all_files.extend(files)

            logger.info(f'Fetched {len(files)} files. Total files: {len(all_files)}')

            next_page_token = results.get('nextPageToken')
            logger.info(f'Next page token: {next_page_token}')
            if not next_page_token or len(all_files) >= max_results:
                logger.info('No more pages to fetch or max results reached')
                break

        return all_files[:max_results]

    async def file_exists(
        self,
        filename: str,
        directory_id: str = None
    ):
        """
        Check if a file exists in Google Drive.

        Args:
            filename (str): The name of the file to check.
            directory_id (str, optional): The ID of the directory to search in. Defaults to None.

        Returns:
            bool: True if the file exists, False otherwise.
        """

        logger.info(f'Checking if file exists: {filename}')

        headers = await self._get_auth_headers()

        req = GoogleDriveFileExistsRequest(
            directory_id=directory_id,
            filename=filename)

        response = await self._http_client.get(
            "https://www.googleapis.com/drive/v3/files",
            headers=headers,
            params=req.to_dict()
        )

        # Check if the file exists
        file_exists = len(response.json().get('files', [])) > 0

        logger.info(f'File exists: {file_exists}')

        return file_exists

    async def resolve_drive_folder_id(self, folder_path: str) -> str:
        """
        Given a folder path like 'Podcasts/CBB', resolve and create (if needed) the folder structure in Google Drive and return the final folder's ID.
        """
        from domain.google import GoogleDriveDirectory
        if not folder_path or folder_path.strip() == "":
            return GoogleDriveDirectory.PodcastDirectoryId

        # Split path and start from root Podcasts folder
        parts = folder_path.strip("/\\").split("/")
        parent_id = GoogleDriveDirectory.PodcastDirectoryId
        for part in parts:
            # Check if folder exists under parent_id
            headers = await self._get_auth_headers()
            query = {
                'q': f"'{parent_id}' in parents and name = '{part}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
                'fields': 'files(id, name)',
                'pageSize': 1
            }
            resp = await self._http_client.get(
                "https://www.googleapis.com/drive/v3/files",
                headers=headers,
                params=query
            )
            if resp.status_code != 200:
                logger.error(f"Failed to check existence of folder '{part}': {resp.status_code} {resp.text}")
                raise Exception(f"Failed to check existence of folder '{part}': {resp.status_code} {resp.text}")
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
                create_resp = await self._http_client.post(
                    "https://www.googleapis.com/drive/v3/files",
                    headers=headers,
                    json=folder_metadata
                )
                if create_resp.status_code not in [200, 201]:
                    logger.error(f"Failed to create folder '{part}': {create_resp.status_code} {create_resp.text}")
                    raise Exception(f"Failed to create folder '{part}': {create_resp.status_code} {create_resp.text}")
                create_json = create_resp.json()
                if 'id' not in create_json:
                    logger.error(f"No 'id' in folder creation response for '{part}': {create_json}")
                    raise Exception(f"No 'id' in folder creation response for '{part}': {create_json}")
                parent_id = create_json['id']
        return parent_id
