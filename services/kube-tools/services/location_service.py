

import asyncio
from threading import Thread
from typing import Any

from data.location_repository import (WeatherStationRepository,
                                      ZipLatLongRepository)
from framework.clients.cache_client import CacheClientAsync
from framework.crypto.hashing import sha256
from framework.logger import get_logger
from framework.serialization import Serializable

logger = get_logger(__name__)


def fire(coroutine):
    asyncio.create_task(coroutine)


def first(items):
    if any(items):
        return items[0]


class GeoSpatialQuery:
    def __init__(self, latitude, longitude, geo_type='Point'):
        self.__latitude = latitude
        self.__longitude = longitude
        self.__geo_type = geo_type

    @property
    def coordinate_pair(self):
        return [
            self.__longitude,
            self.__latitude
        ]

    def get_query(self):
        return {
            'loc': {
                '$near': {
                    '$geometry': {
                        'type': self.__geo_type,
                        'coordinates': self.coordinate_pair
                    }
                }
            }
        }


class RangeFilter:
    def __init__(
        self,
        start: Any,
        end: Any,
        field_name: str
    ):
        self.__start = start
        self.__end = end
        self.__field_name = field_name

    def get_filter(
        self
    ) -> dict:

        return {
            self.__field_name: {
                '$lte': self.__start,
                '$gte': self.__end
            }
        }


class ZipLatLongModel(Serializable):
    @property
    def coordinates(self):
        return self.data.get('loc', dict()).get(
            'coordinates', [])

    @property
    def latitude(self):
        if any(self.coordinates):
            return self.coordinates[1]

    @property
    def longitude(self):
        if any(self.coordinates):
            return self.coordinates[0]

    def __init__(self, data):
        self.key = data.get('key')
        self.zip = data.get('zip')
        self.data = data

    def to_dict(self):
        return super().to_dict() | {
            'coordinates': {
                'lat': self.latitude,
                'lng': self.longitude
            }
        }

    def _exclude(self):
        return ['data']


class StationCoordinateModel(Serializable):
    def __init__(self, data):
        self.lookup_id = data.get('lookup_id')
        self.station_id = data.get('station_id')
        self.latitude = data.get('latitude')
        self.longitude = data.get('longitude')
        self.elevation = data.get('elevation')
        self.station_name = data.get('elevation_name')


class CoordinateRequest:
    @property
    def hash_key(self):
        return sha256(str([
            round(self.longitude, 3),
            round(self.latitude, 3)
        ]))

    @property
    def coordinates(self):
        return [
            self.longitude,
            self.latitude
        ]

    def __init__(self, data):
        self.latitude = data.get('latitude')
        self.longitude = data.get('longitude')


class ZipRequest:
    @property
    def hash_key(self):
        return sha256(self.__zip_code)

    @property
    def zip_code(self):
        if isinstance(self.__zip_code, str):
            return int(self.__zip_code)
        return self.__zip_code

    def __init__(self, data):
        self.__zip_code = data.get('zip_code')


class StationByIdRequest:
    def __init__(self, data):
        self.station_id = data.get('station_id')


class StationByNameRequest:
    def __init__(self, data):
        self.station_name = data.get('station_name')


class LocationNotFoundException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__('Location not found')


class LocationService:
    def __init__(
        self,
        zip_lat_long_repository: ZipLatLongRepository,
        weather_station_repository: WeatherStationRepository,
        cache_client: CacheClientAsync
    ):
        self.__zip_lat_long_repository = zip_lat_long_repository
        self.__weather_station_repository = weather_station_repository
        self.__cache_client = cache_client

    async def get_coordinates_by_zip(
        self,
        zip_request: ZipRequest
    ):
        hash_key = zip_request.hash_key

        logger.info(f'Hash key: {hash_key}')
        cached = await self.__cache_client.get_json(
            key=hash_key)

        if cached is not None:
            logger.info(f'Returning cached @ key: {hash_key}')
            return cached

        result = await self.__zip_lat_long_repository.query({
            'zip': zip_request.zip_code
        })

        if result is None:
            raise LocationNotFoundException()

        model = ZipLatLongModel(
            data=first(result))

        fire(self.__cache_client.set_json(
            key=zip_request.hash_key,
            value=model.to_dict(),
            ttl=15
        ))

        return model.to_dict()

    async def get_zip_by_coordinates(
        self,
        coordinates: CoordinateRequest
    ):
        hash_key = coordinates.hash_key
        logger.info(f'Key: {hash_key}')

        cached = await self.__cache_client.get_json(
            key=hash_key)

        if cached is not None:
            logger.info(f'Returning cache @ key {hash_key}')
            return cached

        geo_query = GeoSpatialQuery(
            latitude=coordinates.latitude,
            longitude=coordinates.longitude).get_query()

        result = await self.__zip_lat_long_repository.query(
            filter=geo_query,
            top=1)

        if result is None:
            raise LocationNotFoundException()

        model = ZipLatLongModel(
            data=first(result))
        result = model.to_dict()

        fire(self.__cache_client.set_json(
            key=hash_key,
            value=result
        ))

        return result

    async def get_station_by_coordinates(self, coordinates: CoordinateRequest):
        pass

    async def get_coordinates_by_station_name(self: StationByNameRequest):
        pass

    async def get_coordinates_by_station_id(self, station: StationByIdRequest):
        pass

    async def get_zip_by_station_id(self, station: StationByIdRequest):
        pass

    async def get_zip_by_station_name(self, station: StationByNameRequest):
        pass

    async def get_station_by_zip(self, zip: ZipRequest):
        pass
