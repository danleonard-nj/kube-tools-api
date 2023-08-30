import base64
import json
from typing import List
from framework.serialization import Serializable
from framework.logger import get_logger
from utilities.utils import KeyUtils, contains, create_uuid

logger = get_logger(__name__)


class CoordinateKey:
    @property
    def key_data(self):
        return {
            'latitude': self.latitude,
            'longitude': self.longitude
        }

    @property
    def key_json(self):
        return json.dumps(self.key_data)

    def __init__(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude

    def get_uuid(self):
        legacy = create_uuid(self.key_data)
        key = KeyUtils.create_uuid(**self.key_data)

        logger.info(
            f'Reverse geo key valiation: {legacy}: {key}: {legacy == key}')
        return key

    def get_compound_key(self):
        return base64.b64encode(self.key_json.encode()).decode()

    @staticmethod
    def from_compound_key(key):
        data = json.loads(
            base64.b64decode(key.encode()).decode())
        return CoordinateKey(**data)


class LocationHistoryReverseGeocodingModel(Serializable):
    def __init__(self, data):
        self.key = data.get('key')
        results_list = data.get('response').get('results', [])

        self.locations = self.get_reverse_geo_list(
            results_list=results_list)


class ReducedGeocodingModel(Serializable):
    def __init__(self, key, locations):
        self.key = key
        self.locations = locations


class ReverseGeocodingModel(Serializable):
    @property
    def results(self):
        return self.response.get('results')

    def __init__(self, data):
        self.key = data.get('key')
        self.latitude = data.get('latitude')
        self.longitude = data.get('longitude')
        self.response = data.get('response')

    @classmethod
    def create_reverse_geocoding_model(
        cls,
        response,
        latitude,
        longitude
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

    def __truncate_reverse_geo_item(self, item):
        return {
            'address': item.get('formatted_address'),
            'place_id': item.get('place_id'),
            'types': item.get('types')
        }

    def get_truncated_data(self) -> List[ReducedGeocodingModel]:
        allowed_types = [
            'formatted_address',
            'premise',
            'neighborhood'
        ]

        filtered_results = filter(
            lambda x: contains(x.get('types', []), allowed_types),
            self.results)

        truncated_locations = [
            self.__truncate_reverse_geo_item(result)
            for result in filtered_results
        ]

        return ReducedGeocodingModel(
            key=self.key,
            locations=truncated_locations
        )


class LocationHistoryModel(Serializable):
    def __init__(self, data):
        self.key = data.get('key')
        self.longitude, self.latitude = data.get(
            'location').get('coordinates')

        self.coordinate_key = self.get_coordinate_key(
            latitude=self.latitude,
            longitude=self.longitude)

        self.device_tag = data.get('deviceTag')
        self.source = data.get('source')
        self.accuracy = data.get('accuracy')
        self.timestamp = data.get('timestamp')

    def get_coordinate_key(self, latitude, longitude):
        return CoordinateKey(
            latitude=latitude,
            longitude=longitude).get_uuid()


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
    def __init__(self, data, include_timestamps):
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

    def meters_to_miles(self, value):
        return round(value * 0.000621371, 2)

    def meters_to_feet(self, value):
        return round(value * 3.28084, 2)

    def get_distance_details(self, meters):
        return {
            'miles': self.meters_to_miles(meters),
            'feet': self.meters_to_feet(meters)
        }

    def get_coordinate_key(self, latitude, longitude):
        return CoordinateKey(
            latitude=latitude,
            longitude=longitude).get_uuid()


class GeocodedDataCoordinateKeyQuery:
    def __init__(self, coordinate_keys):
        self.coordinate_keys = coordinate_keys

    def get_query(self):
        return {
            'coordinate_key': {
                '$in': self.coordinate_keys
            }
        }
