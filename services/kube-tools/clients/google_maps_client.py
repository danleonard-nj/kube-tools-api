from typing import Dict

from domain.google import GoogleMapsException
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url
from httpx import AsyncClient

logger = get_logger(__name__)


class GoogleMapsClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient
    ):
        self._http_client = http_client

        self._base_url = configuration.google_maps.get('base_url')
        self._api_key = configuration.google_maps.get('api_key')

    async def reverse_geocode(
        self,
        latitude,
        longitude
    ) -> Dict:
        endpoint = f'{self._base_url}/maps/api/geocode/json'
        url = build_url(
            base=endpoint,
            latlng=f'{latitude},{longitude}',
            key=self._api_key)

        logger.info(f'Endpoint: {url}')
        response = await self._http_client.get(
            url=url)

        logger.info(f'Response: {response.status_code}')

        if response.status_code != 200:
            raise GoogleMapsException(
                latitude=latitude,
                longitude=longitude)

        return response.json()
