from typing import Any, Dict, List, Tuple

from framework.logger import get_logger

from data.google.google_location_history_repository import \
    GoogleLocationHistoryRepository
from domain.location_history import (LocationAggregatePipeline,
                                     LocationHistoryAggregateModel)
from services.reverse_geocoding_service import GoogleReverseGeocodingService

logger = get_logger(__name__)


class LocationHistoryService:
    def __init__(
        self,
        repository: GoogleLocationHistoryRepository,
        reverse_geo_service: GoogleReverseGeocodingService
    ):
        self.__repository = repository
        self.__reverse_geo_service = reverse_geo_service

    async def get_locations(
        self,
        latitude: float,
        longitude: float,
        max_distance: int,
        limit: int = 50,
        include_timestamps: bool = False
    ):
        logger.info(f'Range {max_distance}')
        logger.info(f'Coordinates: [{latitude}, {longitude}]')
        logger.info(f'Limit: {limit}')

        pipeline = LocationAggregatePipeline(
            latitude=latitude,
            longitude=longitude,
            max_distance=max_distance,
            limit=limit)

        # Query locations on geospatial index
        location_results = await self.__repository.collection.aggregate(
            pipeline=pipeline.get_pipeline(),
            allowDiskUse=True).to_list(length=None)

        # Create location history models
        location_history = self.__get_location_history_aggregate_models(
            location_results=location_results,
            include_timestamps=include_timestamps)

        # No location history results
        if not any(location_history):
            logger.info(f'No results in history: {latitude}: {longitude}')
            return list()

        # Get a list of the distinct coordinate pairs
        coordinate_pairs = self.__get_coordinate_pairs(
            location_history=location_history)

        logger.info(f'Coordinate pairs: {coordinate_pairs}')

        # Reverse geocode all coordinate pairs from result
        reverse_geo = await self.__reverse_geo_service.reverse_geocode(
            coordinate_pairs=coordinate_pairs)

        # Create a lookup of reverse geo data
        reverse_geo_lookup = self.__get_reverse_geo_lookup(
            reverse_geo=reverse_geo)

        for model in location_history:
            reverse_geo_model = reverse_geo_lookup.get(model.coordinate_key)
            model.reverse_geocoded = reverse_geo_model.to_dict()

        return [model.to_dict() for model in location_history]

    def __get_location_history_aggregate_models(
        self,
        location_results,
        include_timestamps: bool
    ) -> List[LocationHistoryAggregateModel]:
        '''
        Create location history result models
        '''

        return [
            LocationHistoryAggregateModel(
                data=result,
                include_timestamps=include_timestamps)
            for result in location_results
        ]

    def __get_coordinate_pairs(
        self,
        location_history
    ) -> List[Tuple[float, float]]:
        '''
        Get coordinate pairs from location history
        '''

        return [
            (model.latitude, model.longitude)
            for model in location_history
        ]

    def __get_reverse_geo_lookup(
        self,
        reverse_geo
    ) -> Dict[str, Any]:
        '''
        Build a lookup for reverse geo results to
        map to location history
        '''

        return {
            rg.key: rg.get_truncated_data()
            for rg in reverse_geo
        }
