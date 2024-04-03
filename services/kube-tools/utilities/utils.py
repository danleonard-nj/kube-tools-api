import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime
from hashlib import md5
from typing import Union

from dateutil import parser
from framework.logger.providers import get_logger

logger = get_logger(__name__)

DEPRECATE_LOGGER_FORMAT = '[%(asctime)-8s] [%(thread)-4s] [%(name)-12s]: [%(levelname)-4s]: %(message)s'


def build_deprecate_logger():
    deprecate_logger = logging.getLogger('deprecated')
    deprecate_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(DEPRECATE_LOGGER_FORMAT)

    file_handler = logging.FileHandler('deprecated.log')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    deprecate_logger.addHandler(file_handler)

    return deprecate_logger


def parse_timestamp(
    value: Union[str, int, datetime]
) -> Union[int, None]:
    '''
    Converts a string, int or datetime to a timestamp
    '''

    if isinstance(value, str):
        return (
            int(value) if value.isnumeric()
            else int(parser.parse(value).timestamp())
        )

    elif isinstance(value, int):
        return value
    elif isinstance(value, datetime):
        return int(value.timestamp())

    raise Exception(f'Unsupported type: {type(value)}')


def parse(value, enum_type):
    if isinstance(value, str):
        try:
            return enum_type(value)
        except:
            return None
    return value


class DateTimeUtil:
    IsoDateTimeFormat = '%Y-%m-%dT%H:%M:%S.%fZ'
    IsoDateFormat = '%Y-%m-%d'

    @staticmethod
    def timestamp() -> int:
        return int(time.time())

    @classmethod
    def get_iso_date(
        cls
    ) -> str:
        return (
            datetime
            .now()
            .strftime(cls.IsoDateFormat)
        )

    @staticmethod
    def iso_from_timestamp(timestamp: int) -> str:
        return (
            datetime
            .fromtimestamp(timestamp)
            .isoformat()
        )


class KeyUtils:
    @staticmethod
    def create_uuid(**kwargs):
        digest = hashlib.md5(json.dumps(
            kwargs,
            default=str).encode())

        return str(uuid.UUID(digest.hexdigest()))


class ValueConverter:
    MegabyteInBytes = 1048576

    @classmethod
    def bytes_to_megabytes(
        cls,
        bytes,
        round_result=True
    ) -> Union[int, float]:

        if bytes == 0:
            return 0

        result = bytes / cls.MegabyteInBytes

        return (
            round(result) if round_result
            else result
        )

    @classmethod
    def megabytes_to_bytes(
        cls,
        megabytes,
        round_result=True
    ) -> Union[int, float]:

        if bytes == 0:
            return 0

        result = cls.MegabyteInBytes * megabytes

        return (
            round(result) if round_result
            else result
        )

    @classmethod
    def gigabytes_to_megabytes(
        cls,
        megabytes,
        round_result=True
    ) -> Union[int, float]:

        result = megabytes * 1024

        return (
            round(result) if round_result
            else result
        )

    @classmethod
    def terabytes_to_gigabytes(
        cls,
        gigabytes,
        round_result=True
    ) -> Union[int, float]:

        result = gigabytes * 1024

        return (
            round(result) if round_result
            else result
        )


def parse_bool(value):
    return value == 'true'


def contains(source_list, substring_list):
    for source_string in source_list:
        for substring in substring_list:
            if substring in source_string:
                return True
    return False


def to_celsius(degrees_fahrenheit, round_digits=2):
    value = (degrees_fahrenheit - 32) * (5/9)
    return round(value, round_digits)


def create_uuid(data):
    text = json.dumps(data, default=str)
    hash_value = md5(text.encode()).hexdigest()
    return str(uuid.UUID(hash_value))


def first(items):
    for item in items:
        return item


def element_at(_list, index):
    try:
        return _list[index]
    except:
        return None


def fire_task(coroutine):
    asyncio.create_task(
        coroutine())


deprecate_logger = build_deprecate_logger()
