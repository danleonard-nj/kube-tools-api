import json
from domain.auth import AuthPolicy
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from framework.di.service_provider import ServiceProvider

from services.redis_service import RedisService
from quart import request

redis_bp = MetaBlueprint('redis_bp', __name__)

logger = get_logger(__name__)


def get_redis_key_value_params(key_name) -> dict:
    return {
        'key_name': key_name,
        'parse_json':  request.args.get('parse_json', '').lower() == 'true'
    }


def get_set_redis_key_value_params(key_name) -> dict:
    return {
        'key_name': key_name,
        'value': request.json
    }


@redis_bp.configure('/api/redis/keys', methods=['GET'], auth_scheme=AuthPolicy.Execute)
async def get_redis_keys(container: ServiceProvider):
    service = container.resolve(RedisService)

    return await service.get_keys()


@redis_bp.configure('/api/redis/keys/<key>', methods=['GET'], auth_scheme=AuthPolicy.Execute)
async def get_redis_key_value(container: ServiceProvider, key: str):
    service: RedisService = container.resolve(RedisService)

    params = get_redis_key_value_params(key)

    return await service.get_value(
        **params)


@redis_bp.configure('/api/redis/keys/<key>', methods=['POST'], auth_scheme=AuthPolicy.Execute)
async def set_redis_key_value(container: ServiceProvider, key: str):
    service: RedisService = container.resolve(RedisService)

    body = await request.get_json()

    return await service.set_value(
        key_name=key,
        body=body
    )


@redis_bp.configure('/api/redis/keys/<key>', methods=['DELETE'], auth_scheme=AuthPolicy.Execute)
async def delete_redis_key(container: ServiceProvider, key: str):
    service = container.resolve(RedisService)

    return await service.delete_key(
        key_name=key)


@redis_bp.configure('/api/redis/flush', methods=['POST'], auth_scheme=AuthPolicy.Execute)
async def flush_redis(container: ServiceProvider):
    service = container.resolve(RedisService)

    return await service.flush()


@redis_bp.configure('/api/redis/diagnostics', methods=['GET'], auth_scheme=AuthPolicy.Execute)
async def get_redis_diagnostics(container: ServiceProvider):
    service = container.resolve(RedisService)

    return await service.get_diagnostics()
