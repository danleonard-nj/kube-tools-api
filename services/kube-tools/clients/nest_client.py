import asyncio
from typing import Dict

import httpx
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace
from httpx import AsyncClient

from domain.cache import CacheKey

logger = get_logger(__name__)


class NestClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        cache_client: CacheClientAsync

    ):
        self.__base_url = configuration.nest.get('base_url')
        self.__token_url = configuration.nest.get('token_url')

        self.__device_id = configuration.nest.get('thermostat_id')
        self.__project_id = configuration.nest.get('project_id')

        self.__client_id = configuration.nest.get('client_id')
        self.__client_secret = configuration.nest.get('client_secret')
        self.__refresh_token = configuration.nest.get('refresh_token')

        self.__http_client = http_client
        self.__cache_client = cache_client

    async def get_token(
        self
    ):
        key = CacheKey.google_nest_auth_token()

        logger.info(f'Nest auth token key: {key}')

        token = await self.__cache_client.get_cache(
            key=key)

        if not none_or_whitespace(token):
            logger.info(f'Using cached nest auth token: {token}')
            return token

        logger.info(f'Fetching token from auth client')
        token = await self.__fetch_token()

        # Cache the Nest auth token
        asyncio.create_task(
            self.__cache_client.set_cache(
                key=key,
                value=token,
                ttl=60))

        logger.info(f'Token fetched: {token}')
        return token

    async def get_headers(
        self
    ):
        token = await self.get_token()

        return {
            'Authorization': f'Bearer {token}'
        }

    async def get_thermostat(
        self
    ) -> Dict:
        headers = await self.get_headers()

        response = await self.__http_client.get(
            url=f'{self.__base_url}/v1/enterprises/{self.__project_id}/devices/{self.__device_id}',
            headers=headers)

        return response.json()

    async def __fetch_token(
        self
    ):
        payload = {
            'grant_type': 'refresh_token',
            'client_id': self.__client_id,
            'client_secret': self.__client_secret,
            'refresh_token': self.__refresh_token
        }

        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                url=self.__token_url,
                data=payload)

            content = response.json()
            return content.get('access_token')
