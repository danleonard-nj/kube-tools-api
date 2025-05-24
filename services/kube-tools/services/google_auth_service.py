from framework.clients.cache_client import CacheClientAsync
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from framework.validators.nulls import none_or_whitespace
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from utilities.utils import fire_task
import datetime
import json

logger = get_logger(__name__)


class GoogleAuthService:
    def __init__(
        self,
        cache_client: CacheClientAsync
    ):
        self._cache_client = cache_client

    async def get_credentials(
        self,
        client_name: str,
        scopes: list[str]
    ) -> Credentials:
        ArgumentNullException.if_none_or_whitespace(client_name, 'client_name')
        ArgumentNullException.if_none(scopes, 'scopes')

        cache_key = f"google_auth:{client_name}:{'-'.join(scopes)}"
        data = await self._cache_client.get_json(key=cache_key)
        if data and 'token' in data and 'refresh_token' in data and 'expiry' in data:
            expiry = datetime.datetime.fromisoformat(data['expiry'])
            if expiry > datetime.datetime.utcnow():
                creds = Credentials(
                    token=data['token'],
                    refresh_token=data['refresh_token'],
                    token_uri=data.get('token_uri'),
                    client_id=data.get('client_id'),
                    client_secret=data.get('client_secret'),
                    scopes=scopes
                )
                return creds

        # If no valid token, try to refresh using refresh_token from redis
        refresh_token = await self._cache_client.get_json(key=f"google_auth_refresh:{client_name}")
        if not refresh_token or 'refresh_token' not in refresh_token:
            raise Exception("No refresh token available. Please set it via the update_refresh_token endpoint.")

        # Always get scopes from client info if not provided or empty
        if not scopes or not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
            client_info = await self._cache_client.get_json(key=f"google_auth_client:{client_name}")
            if not client_info or 'scopes' not in client_info:
                raise Exception("No scopes provided and none found in client info.")
            scopes = client_info['scopes']
            if isinstance(scopes, str):
                scopes = [scopes]

        creds = Credentials(
            token=None,
            refresh_token=refresh_token['refresh_token'],
            token_uri=refresh_token.get('token_uri'),
            client_id=refresh_token.get('client_id'),
            client_secret=refresh_token.get('client_secret'),
            scopes=scopes
        )
        creds.refresh(Request())
        expiry = creds.expiry.isoformat() if creds.expiry else (datetime.datetime.utcnow() + datetime.timedelta(minutes=55)).isoformat()
        token_data = {
            'token': creds.token,
            'refresh_token': creds.refresh_token,
            'expiry': expiry,
            'token_uri': creds.token_uri,
            'client_id': creds.client_id,
            'client_secret': creds.client_secret
        }
        fire_task(self._cache_client.set_json(key=cache_key, value=token_data, ttl=3600))
        return creds

    async def get_token(
        self,
        client_name: str,
        scopes: list[str]
    ):
        creds = await self.get_credentials(client_name, scopes)
        return creds.token

    async def save_client_info(
        self,
        client_name: str,
        client_id: str,
        client_secret: str,
        token_uri: str = "https://oauth2.googleapis.com/token"
    ):
        ArgumentNullException.if_none_or_whitespace(client_name, 'client_name')
        ArgumentNullException.if_none_or_whitespace(client_id, 'client_id')
        ArgumentNullException.if_none_or_whitespace(client_secret, 'client_secret')
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'token_uri': token_uri
        }
        await self._cache_client.set_json(key=f"google_auth_client:{client_name}", value=data, ttl=60*60*24*30)  # 30 days
        logger.info(f"Client info for {client_name} saved in redis.")
        return True

    async def update_refresh_token(
        self,
        client_name: str,
        refresh_token: str
    ):
        ArgumentNullException.if_none_or_whitespace(client_name, 'client_name')
        ArgumentNullException.if_none_or_whitespace(refresh_token, 'refresh_token')
        # Retrieve client info
        client_info = await self._cache_client.get_json(key=f"google_auth_client:{client_name}")
        if not client_info:
            raise Exception("Client info not found. Please save client info first.")
        data = {
            'refresh_token': refresh_token,
            'token_uri': client_info.get('token_uri', "https://oauth2.googleapis.com/token"),
            'client_id': client_info['client_id'],
            'client_secret': client_info['client_secret']
        }
        await self._cache_client.set_json(key=f"google_auth_refresh:{client_name}", value=data, ttl=60*60*24*30)  # 30 days
        logger.info(f"Refresh token for {client_name} updated in redis.")
        return True
