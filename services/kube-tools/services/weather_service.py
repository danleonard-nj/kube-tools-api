import asyncio
from datetime import datetime

import pandas as pd
import pytz
from framework.clients.cache_client import CacheClientAsync
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace

from clients.open_weather_client import OpenWeatherClient
from data.weather_repository import WeatherRepository
from domain.cache import CacheKey
from domain.weather import (FORECAST_AGGREGATE_MAPPING,
                            FORECAST_COLUMN_EXCLUSIONS, TemperatureResult)
from utilities.utils import DateTimeUtil, KeyUtils

logger = get_logger(__name__)

FORECAST_AGGREGATE_KEY = 'date'
DEAULT_TIMEZONE = 'America/Phoenix'


class ForecastRecord:
    def __init__(
        self,
        date: str,
        timestamp: int,
        temperature: float,
        feels_like: float,
        temperature_min: float,
        temperature_max: float,
        pressure: int,
        humidity: int,
        weather_description: str
    ):
        self.date = date
        self.temperature = temperature
        self.feels_like = feels_like
        self.temperature_min = temperature_min
        self.temperature_max = temperature_max
        self.pressure = pressure
        self.humidity = humidity
        self.weather_description = weather_description
        self.timestamp = timestamp


class WeatherService:
    def __init__(
        self,
        configuration: Configuration,
        open_weather_client: OpenWeatherClient,
        weather_repository: WeatherRepository,
        feature_client: FeatureClientAsync,
        cache_client: CacheClientAsync
    ):
        self.__client = open_weather_client
        self.__repository = weather_repository
        self.__cache_client = cache_client

        tz_name = configuration.weather.get(
            'timezone', DEAULT_TIMEZONE)

        self.__timezone = pytz.timezone(tz_name)

    async def get_weather_by_zip(
        self,
        zip_code: str
    ):
        cache_key = CacheKey.weather_by_zip(
            zip_code=zip_code)

        result = await self.__cache_client.get_json(
            key=cache_key)

        if result is not None:
            logger.info(f'Cache hit for key: {cache_key}')
            return result

        result = await self.__fetch_weather_by_zip(
            zip_code=zip_code)

        asyncio.create_task(
            self.__cache_client.set_json(
                key=cache_key,
                value=result,
                ttl=10))

        return result

    async def __fetch_weather_by_zip(
        self,
        zip_code: str
    ):
        logger.info(f'Getting weather for zip: {zip_code}')

        if none_or_whitespace(zip_code) or len(zip_code) != 5:
            return {
                "error": f"Invalid zip code: '{zip_code}'"
            }

        data = await self.__client.get_weather_by_zip(
            zip_code)

        if 'dt' in data:
            logger.info(f'Removing dt from data to create cardinality key')
            del data['dt']

        key = KeyUtils.create_uuid(**data)
        logger.info(f'Cardinality key: {key}')

        if data.get('cod') != 200:
            error_message = data.get("message")

            return {
                'error': error_message
            }

        # Extract relevant weather information
        main = data.get('main')
        weather = data.get('weather')[0]
        sys = data.get('sys')
        coord = data.get('coord')
        wind = data.get('wind')

        record = TemperatureResult(
            location_zipcode=zip_code,
            location_name=data.get('name'),
            latitude=coord.get('lat'),
            longitude=coord.get('lon'),
            temperature=main.get('temp'),
            feels_like=main.get('feels_like'),
            temperature_max=main.get('temp_max'),
            temperature_min=main.get('temp_min'),
            pressure=main.get('pressure'),
            humidity=main.get('humidity'),
            weather_description=weather.get('description'),
            sunrise=sys.get('sunrise'),
            sunset=sys.get('sunset'),
            wind_speed=wind.get('speed'),
            wind_degrees=wind.get('deg'),
            cardinality_key=key,
            response=data,
            timestamp=DateTimeUtil.timestamp())

        logger.info(f'Record: {record.to_dict()}')

        logger.info(
            f'Capturing weather record for {record.location_zipcode}')

        cardinality_key = await self.get_last_synced_cardinality_key(
            zip_code=zip_code)

        is_captured = False
        record_bk = None

        if key != cardinality_key:
            logger.info('Cardinality key mismatch, storing record')

            insert_result = await self.capture_weather_record(
                record=record)

            is_captured = True
            record_bk = insert_result.inserted_id

            logger.info(f'Setting cardinality key: {zip_code}: {key}')
            await self.set_last_synced_cardinality_key(
                zip_code=zip_code,
                cardinality_key=key)

        return {
            'cardinality_key': key,
            'is_captured': is_captured,
            'weather': record.to_dict(),
            'record_bk': record_bk
        }

    async def get_forecast(
        self,
        zip_code: str
    ):
        cache_key = CacheKey.weather_forecast_by_zip(
            zip_code=zip_code)

        result = await self.__cache_client.get_json(
            key=cache_key)

        if result is not None:
            logger.info(f'Cache hit for key: {cache_key}')
            return result

        result = await self.__generate_forecast(
            zip_code=zip_code)

        asyncio.create_task(
            self.__cache_client.set_json(
                key=cache_key,
                value=result,
                ttl=10))

        return result

    async def __generate_forecast(
        self,
        zip_code: str
    ):
        forecast_data = await self.__client.get_forecast(
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
                tz=self.__timezone)

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

            # 3 hour interval updats
            day['details'] = details

        return aggregated_data

    async def capture_weather_record(
        self,
        record: TemperatureResult
    ):
        result = await self.__repository.insert(
            document=record.to_dict())

        logger.info(f'Insert result: {result.inserted_id}')

        return result

    async def get_last_synced_cardinality_key(
        self,
        zip_code: str
    ) -> str:

        cache_key = CacheKey.weather_cardinality_by_zip(
            zip_code=zip_code)
        logger.info(f'Cache key: {cache_key}')

        result = await self.__cache_client.get_cache(
            key=cache_key)

        return result

    async def set_last_synced_cardinality_key(
        self,
        zip_code: str,
        cardinality_key: str
    ) -> str:

        cache_key = CacheKey.weather_cardinality_by_zip(
            zip_code=zip_code)

        logger.info(f'Cache key: {cache_key}')

        result = await self.__cache_client.set_cache(
            key=cache_key,
            value=cardinality_key,
            ttl=60 * 60 * 24 * 7)

        return result
