import base64
import json
from typing import Dict, List

from framework.serialization import Serializable


class CoordinateKey:
    @property
    def key_data(
        self
    ) -> Dict[str, float]:
        return

    @property
    def key_json(self):
        return json.dumps(
            self.__get_key_data())

    def __init__(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude

    def get_uuid(self):
        return create_uuid(self.key_data)

    def get_uuid(
        self
    ) -> str:
        return KeyUtils.create_uuid()


class ReducedGeocodingModel(Serializable):
    def __init__(
        self,
        key: str,
        locations: List
    ):
        self.key = key
        self.locations = locations


class ReverseGeocodingModel(Serializable):
    @property
    def results(
        self
    ):
        return self.response.get('results')

    def __init__(
        self,
        data: Dict
    ):
        self.key = data.get('key')
        self.latitude = data.get('latitude')
        self.longitude = data.get('longitude')
        self.response = data.get('response')

    @classmethod
    def create_reverse_geocoding_model(
        cls,
        response: Dict,
        latitude: float,
        longitude: float
    ):
        key = CoordinateKey(
            latitude=latitude,
            longitude=longitude)

        return ReverseGeocodingModel({
            'key': key.get_uuid(),
            'latitude': latitude,
            'longitude': longitude,
            'response': response
        })


class LocationAggregatePipeline:
    def __init__(self, latitude, longitude, max_distance, limit):
        self.latitude = latitude
        self.longitude = longitude
        self.max_distance = max_distance
        self.limit = limit

    def get_pipeline(self):
        return [
            {
                "$geoNear": {
                    "distanceField": "distance",
                    "maxDistance": self.max_distance,
                    "spherical": True,
                    "near": {
                        "coordinates": [
                            self.longitude,
                            self.latitude
                        ]
                    },
                }
            },
            {
                '$addFields': {
                    'latitude':  {
                        '$round': [{'$arrayElemAt': ['$location.coordinates', 1]}, 3]
                    },
                    'longitude': {
                        '$round': [{'$arrayElemAt': ['$location.coordinates', 0]}, 3]
                    }
                }
            },
            {
                '$group': {
                    '_id': {
                        'latitude': '$latitude',
                        'longitude': '$longitude',
                    },
                    'count': {
                        '$sum': 1
                    },
                    'distance': {
                        '$max': '$distance'
                    },
                    'timestamps': {
                        '$addToSet': '$timestamp'
                    },
                    'maxTimestamp': {
                        '$max': '$timestamp'
                    },
                    'sources': {
                        '$addToSet': '$source'
                    }
                }
            },
            {
                "$sort": {'_id.distance': 1}
            },
            {
                '$limit': self.limit
            }
        ]


class LocationHistoryAggregateModel(Serializable):
    def __init__(
        self,
        data: Dict,
        include_timestamps: bool
    ):

        group_key = data.get('_id')
        distance = data.get('distance')

        self.longitude = group_key.get('longitude')
        self.latitude = group_key.get('latitude')

        self.coordinate_key = self.get_coordinate_key(
            latitude=self.latitude,
            longitude=self.longitude)

        self.distance = self.get_distance_details(
            meters=distance)

        self.count = data.get('count')
        self.sources = data.get('sources')
        self.maxTimestamp = data.get('maxTimestamp')

        if include_timestamps:
            self.timestamps = data.get('timestamps')

    def meters_to_miles(
        self,
        value: float
    ):
        return round(value * 0.000621371, 2)

    def meters_to_feet(
        self,
        value: float
    ):
        return round(value * 3.28084, 2)

    def get_distance_details(
        self,
        meters: float
    ) -> Dict:

        return {
            'miles': self.meters_to_miles(meters),
            'feet': self.meters_to_feet(meters)
        }

    def get_coordinate_key(
        self,
        latitude: float,
        longitude: float
    ) -> CoordinateKey:

        return CoordinateKey(
            latitude=latitude,
            longitude=longitude).get_uuid()


class GeocodedDataCoordinateKeyQuery:
    def __init__(
        self,
        coordinate_keys: List
    ):
        self.coordinate_keys = coordinate_keys

    def get_query(self):
        return {
            'coordinate_key': {
                '$in': self.coordinate_keys
            }
        }
