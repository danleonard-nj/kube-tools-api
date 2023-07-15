from framework.configuration import Configuration

from clients.open_weather_client import OpenWeatherClient
from framework.logger import get_logger
from data.weather_repository import WeatherRepository
from framework.clients.feature_client import FeatureClientAsync
from framework.crypto.hashing import sha256
from framework.validators.nulls import none_or_whitespace
from framework.clients.cache_client import CacheClientAsync
from domain.cache import CacheKey

from domain.weather import TemperatureResult
from utilities.utils import DateTimeUtil, KeyUtils


logger = get_logger(__name__)


class WeatherService:
    def __init__(
        self,
        open_weather_client: OpenWeatherClient,
        weather_repository: WeatherRepository,
        feature_client: FeatureClientAsync,
        cache_client: CacheClientAsync
    ):
        self.__client = open_weather_client
        self.__repository = weather_repository
        self.__cache_client = cache_client

    async def get_weather_by_zip(
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
