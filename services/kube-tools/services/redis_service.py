import json
from typing import Dict
from framework.clients.cache_client import CacheClientAsync
from framework.logger.providers import get_logger
from framework.exceptions.nulls import ArgumentNullException
from framework.serialization import Serializable
from framework.validators.nulls import none_or_whitespace

logger = get_logger(__name__)


def try_parse_json_cache_value(
    key_name: str,
    data: str
):
    try:
        return json.loads(data)
    except Exception as e:
        raise RedisJsonParsingException(
            key_name=key_name,
            error_message=str(e))


class RedisJsonParsingException(Exception):
    def __init__(
        self,
        key_name: str,
        error_message: str
    ):
        super().__init__(
            f"Failed to parse JSON for key: {key_name}: {error_message}")


class RedisKeyNotFoundException(Exception):
    def __init__(
        self,
        key_name: str
    ):
        super().__init__(
            f"No key with the name '{key_name}' exists")


class RedisCacheValueResult(Serializable):
    def __init__(
        self,
        key: str,
        value: bytes | str,
        parse_json: bool = False
    ):
        self.key = key
        if isinstance(value, bytes):
            self.value = value.decode()

        if parse_json:
            self.value = try_parse_json_cache_value(
                key_name=key,
                data=self.value)

    def to_dict(self) -> Dict:
        return {
            'key': self.key,
            'value': self.value
        }


class RedisSetCacheValueRequest:
    def __init__(
        self,
        key_name: str,
        value: str | dict,
        parse_json: bool = False
    ):
        ArgumentNullException.if_none_or_whitespace(key_name, 'key_name')
        ArgumentNullException.if_none_or_whitespace(value, 'value')

        self.key_name = key_name
        self.value = value
        self.parse_json = parse_json

    @staticmethod
    def from_response(
        key_name: str,
        body: dict
    ):
        return RedisSetCacheValueRequest(
            key_name=key_name,
            value=body.get('value'),
            parse_json=body.get('parse_json', False))

    def get_value(
        self
    ):
        if self.parse_json:
            logger.info(f'Parsing JSON for key: {self.key_name}')
            return json.dumps(self.value)

        return self.value


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
        key_name: str,
        parse_json: bool = False
    ) -> RedisCacheValueResult:
        ArgumentNullException.if_none_or_whitespace(key_name, 'key_name')

        logger.info(f'Getting value for key: {key_name}')

        value = await self._cache_client.client.get(key_name)

        if value is None:
            logger.info(f'No value found for key: {key_name}')
            raise Exception(f"No key wtih name '{key_name}' exists")

        result = RedisCacheValueResult(
            key=key_name,
            value=value,
            parse_json=parse_json)

        logger.info(f'Value for key: {key_name}: {result}')

        return result

    async def set_value(
        self,
        key_name: str,
        body: dict
    ):
        ArgumentNullException.if_none_or_whitespace(key_name, 'key_name')

        req = RedisSetCacheValueRequest.from_response(
            key_name=key_name,
            body=body
        )

        logger.info(f'Setting value for key: {key_name}')

        value = req.get_value()
        logger.info(F'Cache value: {value}')

        result = await self._cache_client.client.set(key_name, value)

        logger.info(f'Set result for key: {key_name}: {result}')

        return {
            'key': key_name,
            'value': value,
            'result': result
        }

    async def delete_key(
        self,
        key_name: str
    ):
        ArgumentNullException.if_none_or_whitespace(key_name, 'key_name')

        logger.info(f'Deleting key: {key_name}')

        result = await self._cache_client.delete_key(key_name)

        # If the key doesn't exist, the result will none
        if result is None:
            logger.info(f'No key found for key: {key_name}')
            raise RedisKeyNotFoundException(key_name=key_name)

        return {
            'result': result
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
