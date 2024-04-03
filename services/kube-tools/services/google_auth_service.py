import asyncio
from typing import List

from data.google.google_auth_repository import GoogleAuthRepository
from domain.cache import CacheKey
from domain.exceptions import InvalidGoogleAuthClientException
from domain.google import AuthClient
from framework.clients.cache_client import CacheClientAsync
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
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

    async def save_auth_client(
        self,
        client: Credentials
    ) -> None:

        ArgumentNullException.if_none(client, 'client')

        auth_client = AuthClient.from_client(
            client=client)

        # Cache the client
        fire_task(
            self._cache_client.set_json(
                key=CacheKey.google_auth_client(),
                value=auth_client.to_dict()))

        result = await self._repository.collection.replace_one(
            auth_client.get_selector(),
            auth_client.to_dict(),
            upsert=True
        )

        logger.info(f'Saved Google auth client: {result.raw_result}')

    async def get_auth_client(
        self,
        scopes: List[str]
    ) -> Credentials:

        ArgumentNullException.if_none(scopes, 'scopes')

        key = CacheKey.google_auth_client()

        entity = await self._cache_client.get_json(
            key=key)

        if entity is None:
            logger.info(f'Fetching Google auth client from database')

            # The only record in the collection should be the
            # auth config
            entity = await self._repository.collection.find_one()

        if entity is None:
            raise InvalidGoogleAuthClientException(
                f'No Google auth client found')

        creds = AuthClient.from_entity(
            data=entity)

        # Cache the client
        fire_task(
            self._cache_client.set_json(
                key=key,
                value=creds.to_dict()))

        client = creds.get_credentials(
            scopes=scopes)

        if creds.scopes == client.scopes and not client.expired:
            return client

        logger.info('Refreshing Google auth client')
        client.refresh(Request())

        logger.info(f'Saving Google auth client')
        await self.save_auth_client(client)

        return client
