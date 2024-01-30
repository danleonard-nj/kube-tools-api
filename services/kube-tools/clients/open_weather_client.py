from domain.weather import GetWeatherQueryParams
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url
from httpx import AsyncClient

logger = get_logger(__name__)


class OpenWeatherClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient
    ):
        self.__base_url = configuration.openweather.get('base_url')
        self._api_key = configuration.openweather.get('api_key')

        self._http_client = http_client

    async def get_weather_by_zip(
        self,
        zip_code: str
    ):
        logger.info(f'Getting weather for {zip_code}')

        # Weather request parameters
        query_params = GetWeatherQueryParams(
            zip_code=zip_code,
            api_key=self._api_key)

        logger.info(f'Request: {query_params.to_dict()}')

        # Build the weather forecast endpoint
        endpoint = build_url(
            base=f'{self.__base_url}/data/2.5/weather',
            **query_params.to_dict())

        logger.info(f'Endpoint: {endpoint}')

        # Fetch daily forecast from weather service
        response = await self._http_client.get(
            url=endpoint)

        logger.info(f'Response status: {response.status_code}')

        return response.json()

    async def get_forecast(
        self,
        zip_code: str
    ):
        query_params = GetWeatherQueryParams(
            zip_code=zip_code,
            api_key=self._api_key)

        # Build endpoint for weather request
        endpoint = build_url(
            base=f'{self.__base_url}/data/2.5/forecast',
            **query_params.to_dict())

        logger.info(f'Getting forecast: {endpoint}: {query_params.to_dict()}')

        # Fetch forecast data from weather service
        response = await self._http_client.get(
            url=endpoint)

        logger.info(f'Response status: {response.status_code}')

        return response.json()
