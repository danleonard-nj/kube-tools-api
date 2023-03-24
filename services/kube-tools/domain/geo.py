
class GeoQueryType:
    GeoNear = '$geoNear'
    Near = '$near'


class GeoSpatialPipeline:
    def __init__(self, latitude, longitude, max_distance=None, limit=50):
        self.__latitude = latitude
        self.__longitude = longitude
        self.__max_distance = max_distance
        self.__limit = limit

    @property
    def coordinate_pair(self):
        return [
            self.__longitude,
            self.__latitude
        ]

    def get_pipeline(self):
        return [
            self.__get_max_distance_query(),
            self.__get_limit()
        ]

    def __get_limit(self):
        return {
            '$limit': self.__limit
        }

    def __get_max_distance_query(self):
        return {
            GeoQueryType.GeoNear: {
                'distanceField': "distance",
                'maxDistance': self.__max_distance,
                'spherical': True,
                'near': {
                    'coordinates': [
                        self.__longitude,
                        self.__latitude
                    ]
                }
            }
        }


class LocationHistoryQueryRequest:
    @property
    def range_meters(self):
        return self.miles_to_meters(self.range)

    def __init__(self, data):
        self.latitude = data.get('latitude')
        self.longitude = data.get('longitude')
        self.range = data.get('range')
        self.limit = data.get('limit')
        self.include_timestamps = data.get(
            'include_timestamps', False)

    def miles_to_meters(self, value):
        return round(value / 0.000621371, 5)
