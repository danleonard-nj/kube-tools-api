import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, Response
from services.kube_tools.clients.google_drive_client_async import GoogleDriveClientAsync, GoogleDriveClientAsyncException
from services.google_auth_service import GoogleAuthService
from domain.google import GoogleClientScope
from domain.drive import GoogleDriveUploadRequest, PermissionType, PermissionRole

import aiofiles
import os

@pytest.fixture
def mock_auth_service():
    mock = AsyncMock(spec=GoogleAuthService)
    mock.get_token.return_value = 'test-token'
    return mock

@pytest.fixture
def mock_http_client():
    mock = AsyncMock(spec=AsyncClient)
    return mock

@pytest.fixture
def drive_client(mock_http_client, mock_auth_service):
    return GoogleDriveClientAsync(http_client=mock_http_client, auth_service=mock_auth_service)

@pytest.mark.asyncio
async def test_get_auth_headers(drive_client, mock_auth_service):
    headers = await drive_client._get_auth_headers()
    assert headers == {'Authorization': 'Bearer test-token'}
    mock_auth_service.get_token.assert_awaited_once()

@pytest.mark.asyncio
async def test_create_resumable_upload_session(drive_client, mock_http_client):
    mock_response = MagicMock()
    mock_response.headers = {'Location': 'http://session.url'}
    mock_response.status_code = 200
    mock_http_client.post.return_value = mock_response
    file_metadata = {'name': 'test.txt'}
    url = await drive_client.create_resumable_upload_session(file_metadata)
    assert url == 'http://session.url'
    mock_http_client.post.assert_awaited_once()

@pytest.mark.asyncio
async def test_upload_file_chunk_success(drive_client, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = 'OK'
    mock_http_client.put.return_value = mock_response
    session_url = 'http://session.url'
    total_size = 1000
    start_byte = 0
    chunk = b'data'
    resp = await drive_client.upload_file_chunk(session_url, total_size, start_byte, chunk)
    assert resp.status_code == 200
    mock_http_client.put.assert_awaited_once()

@pytest.mark.asyncio
async def test_upload_file_chunk_retry_error(drive_client, mock_http_client):
    from tenacity import RetryError
    drive_client._cancel_resumable_session = AsyncMock()
    mock_http_client.put.side_effect = RetryError(Exception('fail'), None)
    with pytest.raises(GoogleDriveClientAsyncException):
        await drive_client.upload_file_chunk('url', 100, 0, b'data')
    drive_client._cancel_resumable_session.assert_awaited_once()

@pytest.mark.asyncio
async def test_upload_single(drive_client, mock_http_client, tmp_path):
    file_path = tmp_path / 'file.txt'
    file_path.write_bytes(b'abc')
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'id': 'fileid'}
    mock_http_client.post.return_value = mock_response
    result = await drive_client.upload_single('file.txt', str(file_path))
    assert result['id'] == 'fileid'
    mock_http_client.post.assert_awaited_once()

@pytest.mark.asyncio
async def test_create_permission(drive_client, mock_http_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'id': 'perm-id'}
    mock_http_client.post.return_value = mock_response
    result = await drive_client.create_permission('fileid', PermissionType.ANYONE, PermissionRole.READER, PermissionType.ANYONE)
    assert result['id'] == 'perm-id'
    mock_http_client.post.assert_awaited_once()

@pytest.mark.asyncio
async def test_get_drive_file_details(drive_client, mock_http_client):
    mock_response = MagicMock()
    mock_response.json.side_effect = [
        {'files': [{'id': '1'}], 'nextPageToken': 'token'},
        {'files': [{'id': '2'}], 'nextPageToken': None}
    ]
    mock_http_client.get.return_value = mock_response
    files = await drive_client.get_drive_file_details(max_results=2)
    assert len(files) == 2
    mock_http_client.get.assert_awaited()

@pytest.mark.asyncio
async def test_file_exists_true(drive_client, mock_http_client):
    mock_response = MagicMock()
    mock_response.json.return_value = {'files': [{'id': '1'}]}
    mock_http_client.get.return_value = mock_response
    exists = await drive_client.file_exists('file.txt')
    assert exists is True

@pytest.mark.asyncio
async def test_file_exists_false(drive_client, mock_http_client):
    mock_response = MagicMock()
    mock_response.json.return_value = {'files': []}
    mock_http_client.get.return_value = mock_response
    exists = await drive_client.file_exists('file.txt')
    assert exists is False

# Integration tests would require real credentials and a test Google Drive environment.
# You can add them here using pytest.mark.integration and real HTTP calls if desired.
