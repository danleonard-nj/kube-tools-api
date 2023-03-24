from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.geo import LocationHistoryQueryRequest
from services.location_history_service import LocationHistoryService

location_history_bp = MetaBlueprint('location_history_bp', __name__)


@location_history_bp.configure('/api/location/history/query', methods=['POST'], auth_scheme='default')
async def query_location_history(container):
    service: LocationHistoryService = container.resolve(LocationHistoryService)

    body = await request.get_json()

    query_request = LocationHistoryQueryRequest(
        data=body)

    data = await service.get_locations(
        latitude=query_request.latitude,
        longitude=query_request.longitude,
        max_distance=query_request.range_meters,
        limit=query_request.limit,
        include_timestamps=query_request.include_timestamps)

    return data
