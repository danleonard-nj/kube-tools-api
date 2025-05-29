import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from datetime import datetime

import services.google_auth_service as google_auth_service_mod


@pytest.mark.asyncio
class TestGoogleAuthService:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.mock_repo = AsyncMock()
        self.mock_cache = AsyncMock()
        self.service = google_auth_service_mod.GoogleAuthService(self.mock_repo, self.mock_cache)

    @patch('services.google_auth_service.Credentials')
    @patch('services.google_auth_service.Request')
    async def test_save_client_success(self, mock_request, mock_creds):
        mock_creds.return_value.to_json.return_value = '{"token": "tok", "refresh_token": "ref", "token_uri": "uri", "client_id": "cid", "client_secret": "sec"}'
        mock_creds.return_value.refresh.return_value = None
        self.mock_repo.set_client.return_value = None
        self.mock_cache.client.delete.return_value = None

        result = await self.service.save_client('name', 'cid', 'sec', 'ref')
        assert result is True
        self.mock_repo.set_client.assert_awaited()
        self.mock_cache.client.delete.assert_awaited()

    @patch('services.google_auth_service.Credentials')
    @patch('services.google_auth_service.Request')
    async def test_get_token_from_cache(self, mock_request, mock_creds):
        self.mock_cache.get_cache.return_value = 'cached_token'
        token = await self.service.get_token('name', ['scope1'])
        assert token == 'cached_token'
        self.mock_cache.get_cache.assert_awaited()
        self.mock_repo.get_client.assert_not_awaited()

    @patch('services.google_auth_service.Credentials')
    @patch('services.google_auth_service.Request')
    async def test_get_token_refresh_and_update(self, mock_request, mock_creds):
        self.mock_cache.get_cache.return_value = None
        stored_creds = {
            'refresh_token': 'ref', 'token_uri': 'uri', 'client_id': 'cid', 'client_secret': 'sec',
            'token': 'tok', 'client_name': 'name', 'updated_at': datetime.utcnow().isoformat()
        }
        self.mock_repo.get_client.return_value = stored_creds
        mock_creds.from_authorized_user_info.return_value.valid = False
        mock_creds.from_authorized_user_info.return_value.token = 'new_token'
        mock_creds.from_authorized_user_info.return_value.refresh.return_value = None
        mock_creds.from_authorized_user_info.return_value.to_json.return_value = '{"token": "new_token", "refresh_token": "ref", "token_uri": "uri", "client_id": "cid", "client_secret": "sec"}'

        token = await self.service.get_token('name', ['scope1'])
        assert token == 'new_token'
        self.mock_repo.set_client.assert_awaited()
        self.mock_cache.set_cache.assert_awaited_with(key=ANY, value='new_token', ttl=3000)

    @patch('services.google_auth_service.Credentials')
    @patch('services.google_auth_service.Request')
    async def test_get_token_missing_client(self, mock_request, mock_creds):
        self.mock_cache.get_cache.return_value = None
        self.mock_repo.get_client.return_value = None
        with pytest.raises(Exception, match="No client found with name"):
            await self.service.get_token('missing', ['scope'])

    @patch('services.google_auth_service.Credentials')
    @patch('services.google_auth_service.Request')
    async def test_get_token_missing_required_field(self, mock_request, mock_creds):
        self.mock_cache.get_cache.return_value = None
        self.mock_repo.get_client.return_value = {'client_id': 'cid', 'client_secret': 'sec'}
        with pytest.raises(Exception, match="missing required field"):
            await self.service.get_token('name', ['scope'])
