from data.google.google_auth_repository import GoogleAuthRepository
from domain.cache import CacheKey
from domain.exceptions import InvalidGoogleAuthClientException
from domain.google import AuthClient
from framework.clients.cache_client import CacheClientAsync
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from framework.validators.nulls import none_or_whitespace
from google.auth.transport.requests import Request

logger = get_logger(__name__)


class GoogleAuthService:
    def __init__(
        self,
        repository: GoogleAuthRepository,
        cache_client: CacheClientAsync
    ):
        self._repository = repository
        self._cache_client = cache_client

    async def get_credentials(
        self,
        client_name: str,
        scopes: list[str]
    ):
        ArgumentNullException.if_none_or_whitespace(client_name, 'client_name')
        ArgumentNullException.if_none(scopes, 'scopes')

        # Fetch the client from database
        client = await self._repository.get({
            'client_name': client_name
        })

        if client is None:
            raise InvalidGoogleAuthClientException(
                f"No client with the name '{client_name}' exists")

        client = AuthClient.from_entity(
            data=client)

        creds = client.get_credentials(
            scopes=scopes)

        if creds.valid:
            return creds

        # Refresh the credentials
        logger.info(f'Refreshing Google auth client: {client_name}')
        creds.refresh(Request())

        # Update the stored client
        await self._repository.replace(
            selector=client.get_selector(),
            document=client.to_dict())

        return creds

    async def get_token(
        self,
        client_name: str,
        scopes: list[str]
    ) -> str:

        cache_key = CacheKey.google_auth_service(
            client_name=client_name,
            scopes=scopes)

        token = await self._cache_client.get_cache(
            key=cache_key)

        if not none_or_whitespace(token):
            return token

        client = await self.get_credentials(
            client_name=client_name,
            scopes=scopes)

        # Cache the token for 30 minutes
        await self._cache_client.set_cache(
            key=cache_key,
            value=client.token,
            ttl=30)

        return client.token
