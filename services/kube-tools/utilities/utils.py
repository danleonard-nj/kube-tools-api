import asyncio
import hashlib
import json
import time
import uuid
from datetime import datetime
from hashlib import md5
from typing import Union

from dateutil import parser
from framework.logger.providers import get_logger
import unicodedata

logger = get_logger(__name__)


def parse_timestamp(
    value: Union[str, int, datetime]
) -> Union[int, None]:
    '''
    Converts a string, int or datetime to a timestamp
    '''

    if isinstance(value, str):
        if value.isnumeric():
            return int(value)
        else:
            return int(parser.parse(value).timestamp())

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
    def get_iso_date(cls) -> str:
        return datetime.now().strftime(cls.IsoDateFormat)

    @staticmethod
    def iso_from_timestamp(timestamp: int) -> str:
        return datetime.fromtimestamp(timestamp).isoformat()


class KeyUtils:
    @staticmethod
    def create_uuid(**kwargs):
        digest = hashlib.md5(json.dumps(kwargs, default=str).encode())
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
    return any(substring in source_list for substring in substring_list)


def to_celsius(degrees_fahrenheit, round_digits=2):
    value = (degrees_fahrenheit - 32) * (5/9)
    return round(value, round_digits)


def create_uuid(data):
    text = json.dumps(data, default=str)
    hash_value = md5(text.encode()).hexdigest()

    # Ensure the hash is truncated to 32 characters
    return str(uuid.UUID(hash_value[:32]))


def first(items):
    for item in items:
        return item


def element_at(_list, index):
    try:
        return _list[index]
    except:
        return None


def fire_task(coroutine):
    asyncio.create_task(coroutine)


def clean_unicode(unicode_str):
    return unicodedata.normalize('NFKD', unicode_str).encode('ascii', 'ignore').decode('utf-8')
