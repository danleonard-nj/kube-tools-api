import json
from datetime import datetime
from functools import reduce
from typing import Dict

from framework.crypto.hashing import sha256
from framework.logger import get_logger
from framework.serialization import Serializable
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


def str_concat(series):
    def func(x, y): return f'{x}, {y}' if y not in x else x

    return reduce(func, series)


FORECAST_COLUMN_EXCLUSIONS = [
    'timestamp'
]

FORECAST_AGGREGATE_MAPPING = {
    'temperature': 'max',
    'feels_like': 'max',
    'temperature_min': 'min',
    'temperature_max': 'max',
    'humidity': 'max',
    'rain': 'max',
    'description': str_concat
}

FORECAST_AGGREGATE_KEY = 'date'
DEAULT_TIMEZONE = 'America/Phoenix'


class OpenWeatherException(Exception):
    def __init__(
        self,
        message: str
    ):
        self.message = message
        super().__init__(message)


class TemperatureResult(Serializable):
    def __init__(
        self,
        record_id: str,
        location_zipcode: str,
        location_name: str,
        latitude: float,
        longitude: float,
        temperature: float,
        feels_like: float,
        temperature_min: float,
        temperature_max: float,
        pressure: int,
        humidity: int,
        wind_speed: float,
        wind_degrees: int,
        weather_description: str,
        sunrise: int,
        sunset: int,
        response: dict,
        timestamp: int
    ):
        self.record_id = record_id
        self.location_zipcode = location_zipcode
        self.location_name = location_name
        self.latitude = latitude
        self.longitude = longitude
        self.temperature = temperature
        self.feels_like = feels_like
        self.temperature_min = temperature_min
        self.temperature_max = temperature_max
        self.humidity = humidity
        self.pressure = pressure
        self.wind_speed = wind_speed
        self.wind_degrees = wind_degrees
        self.weather_description = weather_description
        self.sunrise = sunrise
        self.sunset = sunset
        self.response = response
        self.cardinality_key = self.get_cardinality_key()
        self.timestamp = timestamp

    def get_cardinality_key(
        self
    ):
        exclude_keys = ['response',
                        'cardinality_key',
                        'timestamp',
                        'record_id']

        data = {
            key: value for key, value
            in self.to_dict().items()
            if key not in exclude_keys
        }

        return sha256(json.dumps(
            data, sort_keys=True))

    @staticmethod
    def from_entity(
        data: dict
    ):
        return TemperatureResult(
            record_id=data.get('record_id'),
            location_zipcode=data.get('location_zipcode'),
            location_name=data.get('location_name'),
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            temperature=data.get('temperature'),
            feels_like=data.get('feels_like'),
            temperature_min=data.get('temperature_min'),
            temperature_max=data.get('temperature_max'),
            pressure=data.get('pressure'),
            humidity=data.get('humidity'),
            wind_speed=data.get('wind_speed'),
            wind_degrees=data.get('wind_degrees'),
            weather_description=data.get('weather_description'),
            sunrise=data.get('sunrise'),
            sunset=data.get('sunset'),
            response=data.get('response'),
            timestamp=data.get('timestamp')
        )

    @staticmethod
    def from_open_weather_response(
        zip_code: str,
        data: dict
    ) -> 'TemperatureResult':
        main = data.get('main')
        weather = data.get('weather')[0]
        sys = data.get('sys')
        coord = data.get('coord')
        wind = data.get('wind')

        return TemperatureResult(
            record_id=None,
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
            response=data,
            timestamp=DateTimeUtil.timestamp()
        )


class GetWeatherQueryParams(Serializable):
    def __init__(
        self,
        zip_code: str,
        api_key: str
    ):
        self.zip_code = zip_code
        self.api_key = api_key

    def to_dict(
        self
    ) -> Dict:
        return {
            'zip': f'{self.zip_code},us',
            'appid': self.api_key,
            'units': 'imperial'
        }


class GetWeatherByZipResponse(Serializable):
    def __init__(
        self,
        cardinality_key: str,
        is_captured: bool,
        weather: Dict,
        captured_timestamp: int
    ):
        self.cardinality_key = cardinality_key
        self.is_captured = is_captured
        self.weather = weather
        self.captured_timestamp = captured_timestamp

    def to_dict(self) -> Dict:
        return super().to_dict() | {
            'captured_timestamp': datetime.fromtimestamp(
                self.captured_timestamp).isoformat()
        }


class OpenWeatherResponse:
    def __init__(
        self,
        data: dict
    ):
        self.status_code = data.get('cod')
        self.message = data.get('message')
        self.record = data
