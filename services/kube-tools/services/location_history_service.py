from typing import List

from data.google.google_location_history_repository import \
    GoogleLocationHistoryRepository
from domain.location_history import (LocationAggregatePipeline,
                                     LocationHistoryAggregateModel,
                                     LocationHistoryModel)
from framework.logger import get_logger

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

    def transform_location_history_models(self, models: List[LocationHistoryModel]):
        distinct_locations = dict()
        for model in models:
            if not model.coordinate_key in distinct_locations:
                distinct_locations[model.coordinate_key] = {
                    'location': model.to_dict(),
                    'visits': [model.timestamp]
                }
            else:
                distinct_locations[model.coordinate_key]['visits'].append(
                    model.timestamp)

        return list(distinct_locations.values())

    async def get_locations(
        self,
        latitude,
        longitude,
        max_distance,
        limit=50,
        include_timestamps=False
    ):
        logger.info(f'Range {max_distance}')
        logger.info(f'Coordinates: [{latitude}, {longitude}]')
        logger.info(f'Limit: {limit}')

        pipeline = LocationAggregatePipeline(
            latitude=latitude,
            longitude=longitude,
            max_distance=max_distance,
            limit=limit
        )

        results = await self.__repository.collection.aggregate(
            pipeline=pipeline.get_pipeline(),
            allowDiskUse=True).to_list(
                length=None)

        models = [
            LocationHistoryAggregateModel(
                data=result,
                include_timestamps=include_timestamps)
            for result in results
        ]

        coordinate_pairs = [
            (model.latitude, model.longitude)
            for model in models
        ]

        logger.info(f'Coordinate pairs: {coordinate_pairs}')

        reverse_geo = await self.__reverse_geo_service.reverse_geocode(
            coordinate_pairs=coordinate_pairs)

        reverse_geo_lookup = {
            rg.key: rg.get_truncated_data()
            for rg in reverse_geo
        }

        for model in models:
            reverse_geo_model = reverse_geo_lookup.get(model.coordinate_key)
            model.reverse_geocoded = reverse_geo_model.to_dict()

        return [model.to_dict() for model in models]
        # return [model.to_dict() for model in models]

        # location_history_models = [
        #     LocationHistoryModel(data=entity)
        #     for entity in result
        # ]

        # reverse_geo_models = await self.get_reverse_geocode_data_by_pairs(
        #     models=location_history_models)

        # reverse_geo_lookup = {
        #     model.key: model
        #     for model in reverse_geo_models
        # }

        # for model in location_history_models:
        #     reverse_geo = reverse_geo_lookup.get(
        #         model.coordinate_key)
        #     model.reverse_geo = self.truncate_reverse_geo_list(
        #         model=reverse_geo)

        # return self.transform_location_history_models(
        #     models=location_history_models)

        # return [model.to_dict() for model in location_history_models]
