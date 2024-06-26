from domain.auth import AuthPolicy
from domain.redis import RedisDeleteCacheValueRequest, RedisGetCacheValueRequest, RedisSetCacheValueRequest
from framework.di.service_provider import ServiceProvider
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.redis_service import RedisService
from framework.exceptions.rest import HttpException

redis_bp = MetaBlueprint('redis_bp', __name__)

logger = get_logger(__name__)


@redis_bp.configure('/api/redis/keys', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_redis_keys(container: ServiceProvider):
    service: RedisService = container.resolve(RedisService)

    return await service.get_keys()


@redis_bp.configure('/api/redis/get', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def get_redis_key_value(container: ServiceProvider):
    service: RedisService = container.resolve(RedisService)

    body = await request.get_json()

    if body is None:
        raise HttpException('Request body is required', 400)

    req = RedisGetCacheValueRequest.from_request_body(
        data=body)

    return await service.get_value(
        req=req)


@redis_bp.configure('/api/redis/set', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def set_redis_key_value(container: ServiceProvider):
    service: RedisService = container.resolve(RedisService)

    body = await request.get_json()

    if body is None:
        raise HttpException('Request body is required', 400)

    req = RedisSetCacheValueRequest.from_request_body(
        body=body)

    return await service.set_value(
        req=req)


@redis_bp.configure('/api/redis/delete', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def delete_redis_key(container: ServiceProvider):
    service: RedisService = container.resolve(RedisService)

    body = await request.get_json()

    if body is None:
        raise HttpException('Request body is required', 400)

    req = RedisDeleteCacheValueRequest.from_request_body(
        body=body)

    return await service.delete_key(
        req=req)


@redis_bp.configure('/api/redis/flush', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def flush_redis(container: ServiceProvider):
    service = container.resolve(RedisService)

    return await service.flush()


@redis_bp.configure('/api/redis/diagnostics', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_redis_diagnostics(container: ServiceProvider):
    service = container.resolve(RedisService)

    return await service.get_diagnostics()
