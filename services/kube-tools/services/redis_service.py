from domain.redis import (RedisCacheValueResponse,
                          RedisDeleteCacheValueRequest,
                          RedisDeleteCacheValueResponse,
                          RedisDiagnosticsResponse, RedisGetCacheValueRequest,
                          RedisGetKeysResponse, RedisSetCacheValueRequest,
                          RedisSetCacheValueResponse)
from framework.clients.cache_client import CacheClientAsync
from framework.concurrency import TaskCollection
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from framework.validators.nulls import none_or_whitespace

logger = get_logger(__name__)


class RedisService:
    def __init__(
        self,
        cache_client: CacheClientAsync
    ):
        self._cache_client = cache_client

    def get_client(
        self
    ):
        return self._cache_client.client

    async def get_keys(
        self,
        pattern: str = '*'
    ) -> RedisGetKeysResponse:

        logger.info(f'Getting keys with pattern: {pattern}')

        keys = await self._cache_client.client.keys(pattern)

        return RedisGetKeysResponse(
            keys=[x.decode() for x in keys])

    async def get_value(
        self,
        req: RedisGetCacheValueRequest
    ) -> RedisCacheValueResponse:

        logger.info(f'Getting value for key: {req.key_name}')

        tasks = TaskCollection(
            self._cache_client.client.get(req.key_name),
            self._cache_client.client.ttl(req.key_name),
            self._cache_client.client.memory_usage(req.key_name),
        )

        value, ttl, memory_usage = await tasks.run()

        if value is None:
            logger.info(f'No value found for key: {req.key_name}')
            raise Exception(f"No key wtih name '{req.key_name}' exists")

        result = RedisCacheValueResponse(
            key=req.key_name,
            value=value,
            ttl=ttl,
            parse_json=req.parse_json,
            memory_usage=memory_usage)

        logger.info(f'Value for key: {req.key_name}: {result.to_dict()}')

        return result

    async def set_value(
        self,
        req: RedisSetCacheValueRequest
    ) -> RedisSetCacheValueResponse:

        ArgumentNullException.if_none(req, 'req')

        logger.info(f'Setting value for key: {req.key_name}')

        value = req.get_value()
        logger.info(F'Cache value: {value}')

        result = await self._cache_client.client.set(
            name=req.key_name,
            value=value,
            ex=req.ttl)

        logger.info(f'Set result for key: {req.key_name}: {result}')

        return RedisSetCacheValueResponse(
            key=req.key_name,
            value=value,
            result=result)

    async def delete_key(
        self,
        req: RedisDeleteCacheValueRequest
    ) -> RedisDeleteCacheValueResponse:

        ArgumentNullException.if_none(req, 'req')

        if none_or_whitespace(req.key_name):
            raise Exception('No key name provided')

        logger.info(f'Deleting key: {req.key_name}')

        result = await self._cache_client.client.delete(
            req.key_name)

        return RedisDeleteCacheValueResponse(
            deleted_keys=result)

    async def flush(
        self
    ) -> dict:

        result = await self._cache_client.client.flushall()
        logger.info(f'Flush result: {result}')

        return {
            'result': result
        }

    async def get_diagnostics(
        self
    ) -> RedisDiagnosticsResponse:

        logger.info(f'Getting diagnostics')

        tasks = TaskCollection(
            self._cache_client.client.info(),
            self._cache_client.client.memory_stats(),
            self._cache_client.client.client_list(),
            self._cache_client.client.client_info(),
            self._cache_client.client.config_get('*'))

        (info,
         memory_stats,
         client_list,
         client_info,
         config
         ) = await tasks.run()

        return RedisDiagnosticsResponse(
            info=info,
            memory_stats=memory_stats,
            client_list=client_list,
            client_info=client_info,
            config=config)
