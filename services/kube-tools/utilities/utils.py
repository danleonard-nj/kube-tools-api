from datetime import datetime
import hashlib
import json
import uuid
from hashlib import md5
import time

from framework.logger.providers import get_logger

logger = get_logger(__name__)


class DateTimeUtil:
    @staticmethod
    def timestamp():
        return int(time.time())


class KeyUtils:
    @staticmethod
    def create_uuid(**kwargs):
        digest = hashlib.md5(json.dumps(
            kwargs,
            default=str).encode())

        return str(uuid.UUID(digest.hexdigest()))


def parse_bool(value):
    return value == 'true'


def contains(source_list, substring_list):
    for source_string in source_list:
        for substring in substring_list:
            if substring in source_string:
                return True
    return False


def create_uuid(data):
    text = json.dumps(data, default=str)
    hash_value = md5(text.encode()).hexdigest()
    return str(uuid.UUID(hash_value))


def get_sort_key(obj, key):
    if isinstance(obj, dict):
        return obj[key]
    return getattr(obj, key)


def sort_by(items, key):
    if any(items):
        logger.info(f'Sort type: {type(items[0]).__name__}: Key: {key}')
        return sorted(items, key=lambda x: get_sort_key(x, key))


# def build_url(base, **kwargs):
#     url = base
#     if kwargs:
#         url += '?'
#     args = list(kwargs.items())
#     for arg in args:
#         url += str(arg[0])
#         url += '='
#         url += urllib.parse.quote_plus(str(arg[1]))
#         if arg[0] != args[-1][0]:
#             url += '&'
#     return url


def to_celsius(degrees_fahrenheit, round_digits=2):
    value = (degrees_fahrenheit - 32) * (5/9)
    return round(value, round_digits)
