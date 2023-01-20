from framework.auth.configuration import AzureAdConfiguration
from framework.clients.cache_client import CacheClientAsync
from framework.configuration.configuration import Configuration
from framework.constants.constants import ConfigurationKey
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from framework.validators.nulls import none_or_whitespace
from httpx import AsyncClient

from domain.cache import CacheKey

logger = get_logger(__name__)


class IdentityClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        cache_client: CacheClientAsync
    ):
        ArgumentNullException.if_none(configuration, 'configuration')
        ArgumentNullException.if_none(cache_client, 'cache_client')

        self.__http_client = http_client
        self.__cache_client = cache_client
        self.__ad_auth: AzureAdConfiguration = configuration.ad_auth

        self.__clients = dict()
        for client in self.__ad_auth.clients:
            self.add_client(client)

    def add_client(self, config: dict) -> None:
        self.__clients.update({
            config.get('name'): {
                'client_id': config.get(
                    ConfigurationKey.CLIENT_CLIENT_ID),
                'client_secret': config.get(
                    ConfigurationKey.CLIENT_CLIENT_SECRET),
                'grant_type': config.get(
                    ConfigurationKey.CLIENT_GRANT_TYPE),
                'scope': ' '.join(
                    config.get(ConfigurationKey.CLIENT_SCOPE))
            }
        })

    async def get_token(
        self,
        client_name: str,
        scope: str = None
    ):
        cache_key = CacheKey.auth_token(
            client=client_name,
            scope=scope)

        logger.info(f'Auth token key: {cache_key}')

        cached_token = await self.__cache_client.get_cache(
            key=cache_key)

        if not none_or_whitespace(cached_token):
            logger.info(f'{cache_key}: returning cached token')
            return cached_token

        client_credentials = self.__clients.get(client_name)

        if client_credentials is None:
            raise Exception(f'No client exists with the name {client_name}')

        if not none_or_whitespace(scope):
            logger.info(f'Using scope: {scope}')
            client_credentials |= {
                'scope': scope
            }

        logger.info(f'Client credential request: {client_credentials}')

        response = await self.__http_client.post(
            url=self.__ad_auth.identity_url,
            data=client_credentials)

        logger.info(f'Response: {response.status_code}')

        if response.is_error:
            raise Exception(
                f'Failed to fetch auth token: {response.status_code}: {response.text}')

        token = response.json().get(
            'access_token')

        await self.__cache_client.set_cache(
            key=cache_key,
            value=token,
            ttl=60)

        return token

    def get_client(self, client_name):
        if not self.__clients.get(client_name):
            raise Exception(f'No client with the name {client_name} exists')

        return self.__clients.get(client_name)
