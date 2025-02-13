from data.google.google_auth_repository import GoogleAuthRepository
from domain.cache import CacheKey
from domain.exceptions import InvalidGoogleAuthClientException
from domain.google import AuthClient, GetTokenResponse
from framework.clients.cache_client import CacheClientAsync
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from framework.validators.nulls import none_or_whitespace
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from utilities.utils import fire_task

logger = get_logger(__name__)


class GoogleAuthService:
    def __init__(
        self,
        repository: GoogleAuthRepository,
        cache_client: CacheClientAsync
    ):
        self._repository = repository
        self._cache_client = cache_client

    async def get_client(
        self,
        client_name: str
    ):
        ArgumentNullException.if_none_or_whitespace(client_name, 'client_name')

        client = await self._repository.get({
            'client_name': client_name
        })

        if client is None:
            raise InvalidGoogleAuthClientException(
                f"No client with the name '{client_name}' exists")

        return AuthClient.from_entity(
            data=client)

    async def get_credentials(
        self,
        client_name: str,
        scopes: list[str]
    ) -> Credentials:
        ArgumentNullException.if_none_or_whitespace(client_name, 'client_name')
        ArgumentNullException.if_none(scopes, 'scopes')

        # Fetch the client from database
        client = await self.get_client(
            client_name=client_name)

        creds = client.get_credentials(
            scopes=scopes)

        if creds.valid:
            return creds

        # Refresh the credentials
        logger.info(f'Refreshing Google auth client: {client_name}')
        creds.refresh(Request())

        # Update the client with the new credentials
        client.update_credentials(
            credentials=creds)

        await self._repository.replace(
            selector=client.get_selector(),
            document=client.to_dict())

        return creds

    async def get_token(
        self,
        client_name: str,
        scopes: list[str]
    ) -> GetTokenResponse:

        cache_key = CacheKey.google_auth_service(
            client_name=client_name,
            scopes=scopes)

        data = await self._cache_client.get_json(
            key=cache_key)

        if not none_or_whitespace(data):
            return GetTokenResponse.from_entity(
                data=data)

        client = await self.get_credentials(
            client_name=client_name,
            scopes=scopes)

        data = GetTokenResponse.from_credentials(
            creds=client)

        # Cache the token for 30 minutes
        fire_task(
            self._cache_client.set_json(
                key=cache_key,
                value=data.to_dict(),
                ttl=30)
        )

        return GetTokenResponse(
            token=client.token)

    async def refresh_token(
        self,
        client_name: str
    ):
        ArgumentNullException.if_none_or_whitespace(client_name, 'client_name')

        client = await self.get_client(
            client_name=client_name)

        creds = client.get_credentials()

        if creds.valid:
            logger.info(f'Google auth client: {client_name} is already valid')
            return True

        logger.info(f'Refreshing Google auth client: {client_name}')

        creds.refresh(Request())

        client.update_credentials(
            credentials=creds)

        await self._repository.replace(
            selector=client.get_selector(),
            document=client.to_dict())

        # Cache the token for 30 minutes
        fire_task(
            self._cache_client.set_cache(
                key=CacheKey.google_auth_service(
                    client_name=client_name,
                    scopes=client.scopes),
                value=GetTokenResponse.from_credentials(
                    creds).to_dict(),
                ttl=30
            )
        )

        return True
