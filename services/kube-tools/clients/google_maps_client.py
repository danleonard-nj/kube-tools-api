import httpx
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url

logger = get_logger(__name__)


class GoogleMapsClient:
    def __init__(
        self,
        configuration: Configuration
    ):
        self.__base_url = configuration.google_maps.get('base_url')
        self.__api_key = configuration.google_maps.get('api_key')

    async def reverse_geocode(self, latitude, longitude):
        endpoint = f'{self.__base_url}/maps/api/geocode/json'
        url = build_url(
            base=endpoint,
            latlng=f'{latitude},{longitude}',
            key=self.__api_key)

        logger.info(f'Endpoint: {url}')
        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.get(
                url=url)

            logger.info(f'Response: {response.status_code}')

            if response.status_code != 200:
                raise Exception(
                    f"Failed to fetch reverse geocode data for coordinate pair: {latitude}, {longitude}")

            return response.json()
