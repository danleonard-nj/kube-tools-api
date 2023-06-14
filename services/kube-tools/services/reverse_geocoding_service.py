from typing import List, Tuple, Union, TypeVar

from framework.concurrency import TaskCollection

from clients.google_maps_client import GoogleMapsClient
from data.google.google_reverse_geocode_repository import \
    GoogleReverseGeocodingRepository
from domain.location_history import CoordinateKey, ReverseGeocodingModel


def first(items):
    if any(items):
        return items[0]


class GoogleReverseGeocodingService:
    def __init__(
        self,
        reverse_geo_repository: GoogleReverseGeocodingRepository,
        google_maps_client: GoogleMapsClient
    ):
        self.__reverse_geo_repository = reverse_geo_repository
        self.__google_maps_client = google_maps_client

    async def reverse_geocode(
        self,
        coordinate_pairs
    ) -> List[ReverseGeocodingModel]:

        fetch_tasks = TaskCollection()

        for pair in coordinate_pairs:
            fetch_tasks.add_task(
                self.get_or_fetch_reverse_geocode(
                    coordinate_pair=pair))

        return await fetch_tasks.run()

    async def get_or_fetch_reverse_geocode(
        self,
        coordinate_pair: Tuple[Union[float, int], Union[float, int]]
    ) -> ReverseGeocodingModel:

        latitude, longitude = coordinate_pair
        key = CoordinateKey(
            latitude=latitude,
            longitude=longitude).get_uuid()

        result = await self.__reverse_geo_repository.get_by_key(
            key=key)
        entity = first(result)

        if entity is not None:
            return ReverseGeocodingModel(
                data=entity)

        result = await self.__google_maps_client.reverse_geocode(
            latitude=latitude,
            longitude=longitude)

        model = ReverseGeocodingModel.create_reverse_geocoding_model(
            response=result,
            latitude=latitude,
            longitude=longitude)

        await self.__reverse_geo_repository.insert(
            document=model.to_dict())

        return model
