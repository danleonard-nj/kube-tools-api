from typing import Dict


class GeoQueryType:
    GeoNear = '$geoNear'
    Near = '$near'


class GeoSpatialPipeline:
    def __init__(
        self,
        latitude: float,
        longitude: float,
        max_distance: int = None,
        limit: int = 50
    ):
        self._latitude = latitude
        self._longitude = longitude
        self._max_distance = max_distance
        self._limit = limit

    @property
    def coordinate_pair(
        self
    ) -> list[float]:
        return [
            self._longitude,
            self._latitude
        ]

    def get_pipeline(
        self
    ) -> Dict:
        return [
            self._get_max_distance_query(),
            self._get_limit()
        ]

    def _get_limit(
        self
    ) -> dict:
        return {
            '$limit': self._limit
        }

    def _get_max_distance_query(
        self
    ) -> dict:
        return {
            GeoQueryType.GeoNear: {
                'distanceField': "distance",
                'maxDistance': self._max_distance,
                'spherical': True,
                'near': {
                    'coordinates': [
                        self._longitude,
                        self._latitude
                    ]
                }
            }
        }


class LocationHistoryQueryRequest:
    @property
    def range_meters(
        self
    ) -> float:

        return self.miles_to_meters(
            self.range)

    def __init__(
        self,
        data: Dict
    ):
        self.latitude = data.get('latitude')
        self.longitude = data.get('longitude')
        self.range = data.get('range')
        self.limit = data.get('limit')
        self.include_timestamps = data.get(
            'include_timestamps', False)

    def miles_to_meters(
        self,
        value: int
    ) -> float:
        return round(value / 0.000621371, 5)
