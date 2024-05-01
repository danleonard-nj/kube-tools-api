from domain.cache import CacheKey
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from utilities.utils import fire_task

logger = get_logger(__name__)


class GoogleAuthClientError(Exception):
    pass


class GoogleAuthClient:
    def __init__(
        self,
        configuration: Configuration,
        cache_client: CacheClientAsync
    ):
        self._configuration = configuration
        self._cache_client = cache_client

    async def get_client(
        self,
        scopes: list[str] = []
    ):
        ArgumentNullException.if_none(scopes, 'scopes')

        data = self._configuration.google_auth

        if data is None:
            raise GoogleAuthClientError('Auth configuration is not set')

        return Credentials.from_authorized_user_info(
            info=data,
            scopes=scopes)

    async def get_token(
        self,
        scopes: list[str]
    ) -> str:

        ArgumentNullException.if_none(scopes, 'scopes')

        cache_key = CacheKey.google_auth_client(
            scopes=scopes)

        token = await self._cache_client.get_cache(
            key=cache_key)

        if not none_or_whitespace(token):
            return token

        client = await self.get_client(
            scopes=scopes)

        if not client.valid:
            logger.info(f'Refreshing Google auth client: {scopes}')
            client.refresh(Request())

        # Cache the token for 30 minutes
        fire_task(self._cache_client.set_cache(
            key=cache_key,
            value=client.token,
            ttl=45))

        return client.token
