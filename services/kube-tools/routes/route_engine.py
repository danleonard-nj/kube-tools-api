from pydantic import BaseModel
from domain.auth import AuthPolicy
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request, abort
from models.googe_maps_models import DirectionsRequestModel
from services.route_engine.route_engine_service import RouteEngineService

logger = get_logger(__name__)

route_engine_bp = MetaBlueprint('route_engine_bp', __name__)


class RouteEnginePromptRequest(BaseModel):
    prompt: str


@route_engine_bp.configure('/api/routes', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_routes(container):
    service: RouteEngineService = container.resolve(RouteEngineService)

    data = await request.get_json()
    if not data:
        abort(400, description="Request body is empty.")

    validated_model = DirectionsRequestModel.model_validate(data)

    result = await service.get_route(
        data=validated_model)

    return result.model_dump()


@route_engine_bp.configure('/api/prompt', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_prompt(container):
    service: RouteEngineService = container.resolve(RouteEngineService)

    data = await request.get_json()
    if not data:
        abort(400, description="Request body is empty.")

    validated_model = RouteEnginePromptRequest.model_validate(data)

    result = await service.get_route_with_natural_language(
        prompt=validated_model.prompt)

    return result
