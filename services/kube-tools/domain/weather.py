from functools import reduce
from typing import Dict

from framework.logger import get_logger
from framework.serialization import Serializable

logger = get_logger(__name__)


FORECAST_COLUMN_EXCLUSIONS = [
    'timestamp'
]


def str_concat(series):
    def func(x, y): return f'{x}, {y}' if y not in x else x

    return reduce(func, series)


FORECAST_AGGREGATE_MAPPING = {
    'temperature': 'max',
    'feels_like': 'max',
    'temperature_min': 'min',
    'temperature_max': 'max',
    'humidity': 'max',
    'rain': 'max',
    'description': str_concat
}


class TemperatureResult(Serializable):
    def __init__(
        self,
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
        response: Dict,
        cardinality_key: str,
        timestamp: int
    ):
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
        self.cardinality_key = cardinality_key
        self.timestamp = timestamp


class GetWeatherQueryParams(Serializable):
    def __init__(
        self,
        zip_code: str,
        api_key: str
    ):
        self.__zip_code = zip_code
        self.__api_key = api_key

    def to_dict(
        self
    ) -> Dict:
        return {
            'zip': f'{self.__zip_code},us',
            'appid': self.__api_key,
            'units': 'imperial'
        }
