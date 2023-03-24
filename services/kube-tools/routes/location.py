from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from services.location_service import (CoordinateRequest, LocationService,
                                       ZipRequest)

location_bp = MetaBlueprint('location_bp', __name__)


@location_bp.configure('/api/location/coordinates/by/zip', methods=['POST'], auth_scheme='default')
async def coordinates_by_zip(container):
    service: LocationService = container.resolve(LocationService)

    body = await request.get_json()

    zip_request = ZipRequest(
        data=body)

    data = await service.get_coordinates_by_zip(
        zip_request=zip_request)

    return data


@location_bp.configure('/api/location/zip/by/coordinates', methods=['POST'], auth_scheme='default')
async def zip_by_coordinates(container):
    service: LocationService = container.resolve(LocationService)

    body = await request.get_json()

    coordinate_request = CoordinateRequest(
        data=body)

    data = await service.get_zip_by_coordinates(
        coordinates=coordinate_request)

    return data
