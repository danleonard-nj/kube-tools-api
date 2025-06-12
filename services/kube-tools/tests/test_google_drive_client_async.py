from clients.google_drive_client_async import GoogleDriveClientAsync, GoogleDriveClientAsyncException
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import os
import sys
import pathlib

# Add the clients directory to sys.path for import resolution
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'clients'))


@pytest_asyncio.fixture
def mock_auth_service():
    mock = AsyncMock()
    mock.get_token.return_value = 'fake-token'
    return mock


@pytest_asyncio.fixture
def mock_http_client():
    mock = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_get_auth_headers(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    headers = await client._get_auth_headers()
    assert headers['Authorization'] == 'Bearer fake-token'


@pytest.mark.asyncio
async def test_create_resumable_upload_session_success(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {'Location': 'http://upload-session-url'}
    mock_response.text = ''
    mock_http_client.post.return_value = mock_response
    session_url = await client.create_resumable_upload_session({'name': 'file.txt'})
    assert session_url == 'http://upload-session-url'


@pytest.mark.asyncio
async def test_create_resumable_upload_session_no_location(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.text = ''
    mock_http_client.post.return_value = mock_response
    session_url = await client.create_resumable_upload_session({'name': 'file.txt'})
    assert session_url is None


@pytest.mark.asyncio
async def test_upload_file_chunk_success(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = 'ok'
    mock_http_client.put.return_value = mock_response
    result = await client.upload_file_chunk('http://session', 100, 0, b'data')
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_upload_large_file_file_not_found(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    with patch('os.path.exists', return_value=False):
        with pytest.raises(GoogleDriveClientAsyncException):
            await client.upload_large_file('file.txt', '/notfound/file.txt')


@pytest.mark.asyncio
async def test_upload_single_success(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'id': 'fileid'}
    mock_http_client.post.return_value = mock_response
    with patch('aiofiles.open', new_callable=MagicMock):
        with patch('builtins.open', new_callable=MagicMock):
            result = await client.upload_single('file.txt', '/tmp/file.txt')
            assert 'id' in result


@pytest.mark.asyncio
async def test_create_permission_success(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {'id': 'perm-id'}
    mock_http_client.post.return_value = mock_response
    # Provide all required arguments, including 'type'
    result = await client.create_permission('fileid', 'anyone', 'reader', 'anyone')
    assert result['id'] == 'perm-id'


@pytest.mark.asyncio
async def test_file_exists_true(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    mock_response = MagicMock()
    mock_response.json.return_value = {'files': [{'id': 'fileid'}]}
    mock_http_client.get.return_value = mock_response
    # Pass directory_id as empty string to avoid Pydantic error
    exists = await client.file_exists('file.txt', directory_id='')
    assert exists


@pytest.mark.asyncio
async def test_file_exists_false(mock_http_client, mock_auth_service):
    client = GoogleDriveClientAsync(mock_http_client, mock_auth_service)
    mock_response = MagicMock()
    mock_response.json.return_value = {'files': []}
    mock_http_client.get.return_value = mock_response
    # Pass directory_id as empty string to avoid Pydantic error
    exists = await client.file_exists('file.txt', directory_id='')
    assert not exists
