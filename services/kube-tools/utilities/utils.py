import json
import uuid
from hashlib import md5

from framework.logger.providers import get_logger

logger = get_logger(__name__)


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
