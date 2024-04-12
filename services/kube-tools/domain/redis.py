import json
from typing import Dict

from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from framework.serialization import Serializable

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


class RedisCacheValueResponse(Serializable):
    def __init__(
        self,
        key: str,
        value: bytes | str,
        ttl: int,
        parse_json: bool = False,
        memory_usage: int = 0
    ):
        self.key = key
        if isinstance(value, bytes):
            self.value = value.decode()

        if parse_json:
            self.value = try_parse_json_cache_value(
                key_name=key,
                data=self.value)

        self.ttl = ttl
        self.parse_json = parse_json
        self.memory_usage = memory_usage


class RedisSetCacheValueResponse(Serializable):
    def __init__(
        self,
        key: str,
        value: str | dict,
        result: bool
    ):
        self.key = key
        self.value = value
        self.result = result


class RedisGetCacheValueRequest:
    def __init__(
        self,
        key_name: str,
        parse_json: bool = False
    ):
        ArgumentNullException.if_none_or_whitespace(key_name, 'key_name')

        self.key_name = key_name
        self.parse_json = parse_json

    @staticmethod
    def from_request_body(
        data: dict
    ):
        return RedisGetCacheValueRequest(
            key_name=data.get('key_name'),
            parse_json=data.get('parse_json', False))


class RedisDeleteCacheValueRequest:
    def __init__(
        self,
        key_name: str
    ):
        self.key_name = key_name

    @staticmethod
    def from_request_body(
        data: dict
    ):
        return RedisDeleteCacheValueRequest(
            key_name=data.get('key_name'))


class RedisSetCacheValueRequest:
    def __init__(
        self,
        key_name: str,
        value: str | dict,
        ttl: int,
        parse_json: bool = False
    ):
        ArgumentNullException.if_none_or_whitespace(key_name, 'key_name')
        ArgumentNullException.if_none_or_whitespace(value, 'value')

        self.key_name = key_name
        self.value = value
        self.ttl = ttl
        self.parse_json = parse_json

    @staticmethod
    def from_request_body(
        body: dict
    ):
        return RedisSetCacheValueRequest(
            key_name=body.get('key_name'),
            value=body.get('value'),
            ttl=body.get('ttl'),
            parse_json=body.get('parse_json', False))

    def get_value(
        self
    ):
        if self.parse_json:
            logger.info(f'Parsing JSON for key: {self.key_name}')
            return json.dumps(self.value)

        return self.value


class RedisDiagnosticsResponse(Serializable):
    def __init__(
        self,
        info,
        memory_stats,
        client_list,
        client_info,
        config
    ):
        self.memory_stats = memory_stats
        self.client_list = client_list
        self.client_info = client_info
        self.config = config
        self.info = info

        for client in client_list:
            client['current'] = str(client.get('id')) == str(
                client_info.get('id'))

    def to_dict(self) -> Dict:
        return {
            'stats': {
                'memory': self.memory_stats,
            },
            'client': {
                'current': self.client_info,
                'list': self.client_list,
            },
            'server': {
                'config': self.config,
                'info': self.info
            }
        }


class RedisGetKeysResponse(Serializable):
    def __init__(
        self,
        keys: list[str]
    ):
        self.keys = keys


class RedisDeleteCacheValueResponse(Serializable):
    def __init__(
        self,
        deleted_keys: int
    ):
        self.deleted_keys = deleted_keys
