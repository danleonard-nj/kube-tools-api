from datetime import datetime

import pandas as pd
import pytz
from clients.open_weather_client import OpenWeatherClient
from data.weather_repository import WeatherRepository
from domain.cache import CacheKey
from domain.weather import (DEAULT_TIMEZONE, FORECAST_AGGREGATE_KEY,
                            FORECAST_AGGREGATE_MAPPING,
                            FORECAST_COLUMN_EXCLUSIONS,
                            GetWeatherByZipResponse, OpenWeatherException,
                            OpenWeatherResponse, TemperatureResult)
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

from utilities.utils import fire_task

logger = get_logger(__name__)

USE_CACHED_RESPONSE = True


class WeatherService:
    def __init__(
        self,
        configuration: Configuration,
        open_weather_client: OpenWeatherClient,
        weather_repository: WeatherRepository,
        cache_client: CacheClientAsync
    ):
        self._client = open_weather_client
        self._repository = weather_repository
        self._cache_client = cache_client

        tz_name = configuration.weather.get(
            'timezone', DEAULT_TIMEZONE)

        self._timezone = pytz.timezone(tz_name)

    async def get_weather_by_zip(
        self,
        zip_code: str
    ):

        ArgumentNullException.if_none_or_whitespace(
            zip_code, 'zip_code')

        if USE_CACHED_RESPONSE:
            cache_key = CacheKey.weather_by_zip(
                zip_code=zip_code)

            result = await self._cache_client.get_json(
                key=cache_key)

            if result is not None:
                logger.info(f'Cache hit for key: {cache_key}')
                return result

        result = await self._fetch_weather_by_zip(
            zip_code=zip_code)

        if USE_CACHED_RESPONSE:
            fire_task(
                self._cache_client.set_json(
                    key=cache_key,
                    value=result,
                    ttl=10))

        return result

    async def _fetch_weather_by_zip(
        self,
        zip_code: str
    ):
        ArgumentNullException.if_none_or_whitespace(
            zip_code, 'zip_code')

        if len(zip_code) != 5:
            raise OpenWeatherException(f"Invalid zip code: '{zip_code}'")

        data = await self._client.get_weather_by_zip(
            zip_code)

    async def _fetch_weather_by_zip(
        self,
        zip_code: str
    ):
        ArgumentNullException.if_none_or_whitespace(
            zip_code, 'zip_code')

        logger.info(f'Getting weather for zip: {zip_code}')

        if len(zip_code) != 5:
            raise OpenWeatherException(f"Invalid zip code: '{zip_code}'")

        data = await self._client.get_weather_by_zip(
            zip_code)

        response = OpenWeatherResponse(
            data=data)

        if response.status_code != 200:
            logger.info(f'Error message: {response.message}')
            raise OpenWeatherException(response.message)

        weather = TemperatureResult.from_open_weather_response(
            zip_code=zip_code,
            data=data)

        # Fetch the cached cardinality key
        cardinality_key = await self.get_last_synced_cardinality_key(
            zip_code=zip_code)

        logger.info(f'Last cardinality key: {cardinality_key}')

        # If no changes have been made, return the last stored record
        if weather.cardinality_key == cardinality_key:

            logger.info('Cardinality key match, returning stored record')

            entity = await self._repository.get_weather_by_zip_cardinality_key(
                zip_code=zip_code,
                cardinality_key=cardinality_key)

            stored_weather = TemperatureResult.from_entity(
                entity)

            return GetWeatherByZipResponse(
                cardinality_key=weather.cardinality_key,
                is_captured=False,
                weather=stored_weather.to_dict(),
                captured_timestamp=stored_weather.timestamp)

        # If the cardinality key has changed, store the record
        logger.info('Cardinality key mismatch, storing record')

        await self.capture_weather_record(
            record=weather)

        logger.info(
            f'Setting cardinality key: {zip_code}: {weather.cardinality_key}')

        await self.set_last_synced_cardinality_key(
            zip_code=zip_code,
            cardinality_key=weather.cardinality_key)

        return GetWeatherByZipResponse(
            cardinality_key=weather.cardinality_key,
            is_captured=True,
            weather=weather.to_dict(),
            captured_timestamp=weather.timestamp)

    async def get_forecast(
        self,
        zip_code: str
    ):

        ArgumentNullException.if_none_or_whitespace(
            zip_code, 'zip_code')

        cache_key = CacheKey.weather_forecast_by_zip(
            zip_code=zip_code)

        result = await self._cache_client.get_json(
            key=cache_key)

        if result is not None:
            logger.info(f'Cache hit for key: {cache_key}')
            return result

        result = await self._generate_forecast(
            zip_code=zip_code)

        fire_task(
            self._cache_client.set_json(
                key=cache_key,
                value=result,
                ttl=10))

        return result

    async def _generate_forecast(
        self,
        zip_code: str
    ):

        ArgumentNullException.if_none_or_whitespace(
            zip_code, 'zip_code')

        forecast_data = await self._client.get_forecast(
            zip_code=zip_code)

        data = forecast_data.get('list')

        forecast_data = []
        for record in data:
            main = record.get('main')
            rain = record.get('rain')
            weather = record.get('weather', [])

            # Parse the record date from the timestamp
            timestamp = record.get('dt')

            parsed_date = datetime.fromtimestamp(
                timestamp,
                tz=self._timezone)

            parsed_date = parsed_date.strftime('%Y-%m-%d')

            logger.info(f'Handling forecast segment for day: {parsed_date}')

            record = {
                'date': parsed_date,
                'timestamp': timestamp,
                'temperature': main.get('temp'),
                'feels_like': main.get('feels_like'),
                'temperature_min': main.get('temp_min'),
                'temperature_max': main.get('temp_max'),
                'humidity': main.get('humidity'),
            }

            record['description'] = (
                weather[0].get('description')
                if any(weather) else 'N/A'
            )

            record['rain'] = (
                (rain.get('3h') * 100)
                if rain is not None else 0
            )

            forecast_data.append(record)

        logger.info(f'Building dataframe')
        df = pd.DataFrame(forecast_data)

        df = df[[
            x for x in df.columns
            if x not in FORECAST_COLUMN_EXCLUSIONS
        ]]

        df = df.sort_values(by=['date'], ascending=True)

        logger.info(
            f'Grouping by aggregate definition: {FORECAST_AGGREGATE_MAPPING}')

        aggregated_data = (df
                           .groupby(FORECAST_AGGREGATE_KEY)
                           .aggregate(FORECAST_AGGREGATE_MAPPING)
                           .reset_index()
                           .to_dict(orient='records'))

        for day in aggregated_data:

            day['description'] = day['description'].split(', ')

            details = []
            for record in forecast_data:
                if record['date'] == day['date']:

                    parsed = datetime.fromtimestamp(
                        record['timestamp'])
                    # Include the full date in the date at the
                    # detail level
                    record['date'] = parsed.isoformat()

                    details.append(record)

            # 3 hour interval updates
            day['details'] = details

        return aggregated_data

    async def capture_weather_record(
        self,
        record: TemperatureResult
    ):

        ArgumentNullException.if_none(record, 'record')

        result = await self._repository.insert(
            document=record.to_dict())

        logger.info(f'Insert result: {result.inserted_id}')

        return result

    async def get_last_synced_cardinality_key(
        self,
        zip_code: str
    ) -> str:

        ArgumentNullException.if_none_or_whitespace(
            zip_code, 'zip_code')

        cache_key = CacheKey.weather_cardinality_by_zip(
            zip_code=zip_code)
        logger.info(f'Cache key: {cache_key}')

        result = await self._cache_client.get_cache(
            key=cache_key)

        return result

    async def set_last_synced_cardinality_key(
        self,
        zip_code: str,
        cardinality_key: str
    ) -> str:

        ArgumentNullException.if_none_or_whitespace(
            zip_code, 'zip_code')
        ArgumentNullException.if_none_or_whitespace(
            cardinality_key, 'cardinality_key')

        cache_key = CacheKey.weather_cardinality_by_zip(
            zip_code=zip_code)

        logger.info(f'Cache key: {cache_key}')

        result = await self._cache_client.set_cache(
            key=cache_key,
            value=cardinality_key,
            ttl=60 * 60 * 24 * 7)

        return result
