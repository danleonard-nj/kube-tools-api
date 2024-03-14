from domain.redis import (RedisCacheValueResponse, RedisGetCacheValueRequest,
                          RedisSetCacheValueRequest)
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

    async def get_keys(
        self,
        pattern: str = '*'
    ):
        logger.info(f'Getting keys with pattern: {pattern}')

        keys = await self._cache_client.client.keys(pattern)

        results = [x.decode() for x in keys]

        return {
            'keys': results
        }

    async def get_value(
        self,
        body: dict
    ) -> RedisCacheValueResponse:

        req = RedisGetCacheValueRequest.from_request_body(
            data=body)

        logger.info(f'Getting value for key: {req.key_name}')

        tasks = TaskCollection(
            self._cache_client.client.get(req.key_name),
            self._cache_client.client.ttl(req.key_name)
        )

        value, ttl = await tasks.run()

        if value is None:
            logger.info(f'No value found for key: {req.key_name}')
            raise Exception(f"No key wtih name '{req.key_name}' exists")

        result = RedisCacheValueResponse(
            key=req.key_name,
            value=value,
            ttl=ttl,
            parse_json=req.parse_json)

        logger.info(f'Value for key: {req.key_name}: {result}')

        return result

    async def set_value(
        self,
        body: dict
    ):
        req = RedisSetCacheValueRequest.from_request_body(
            body=body)

        logger.info(f'Setting value for key: {req.key_name}')

        value = req.get_value()
        logger.info(F'Cache value: {value}')

        result = await self._cache_client.client.set(
            name=req.key_name,
            value=value,
            ex=req.ttl)

        logger.info(f'Set result for key: {req.key_name}: {result}')

        return {
            'key': req.key_name,
            'value': value,
            'result': result
        }

    async def delete_key(
        self,
        body: dict
    ):
        ArgumentNullException.if_none(body, 'body')

        key_name = body.get('key_name')

        if none_or_whitespace(key_name):
            raise Exception('No key name provided')

        logger.info(f'Deleting key: {key_name}')

        result = await self._cache_client.client.delete(key_name)

        return {
            'deleted_keys': result
        }

    async def flush(
        self
    ):
        logger.info(f'Flushing cache')

        result = await self._cache_client.client.flushall()
        logger.info(f'Flush result: {result}')

        return {
            'result': result
        }

    async def get_diagnostics(
        self
    ):
        logger.info(f'Getting diagnostics')

        return await self._cache_client.client.info()
