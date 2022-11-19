import asyncio
import urllib
from datetime import datetime
from typing import Union

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from framework.logger.providers import get_logger
from hashlib import md5
import uuid
import json

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


def none_or_whitespace(value):
    return value is None or value == ''


def get_sort_key(obj, key):
    if isinstance(obj, dict):
        return obj[key]
    return getattr(obj, key)


def sort_by(items, key):
    if any(items):
        logger.info(f'Sort type: {type(items[0]).__name__}: Key: {key}')
        return sorted(items, key=lambda x: get_sort_key(x, key))


def build_url(base, **kwargs):
    url = base
    if kwargs:
        url += '?'
    args = list(kwargs.items())
    for arg in args:
        url += str(arg[0])
        url += '='
        url += urllib.parse.quote_plus(str(arg[1]))
        if arg[0] != args[-1][0]:
            url += '&'
    return url


def element_at(_list, index):
    try:
        return _list[index]
    except:
        return None


def getattr_or_none(obj, name):
    if hasattr(obj, name):
        return getattr(obj, name)
    return None


class DeferredTasks:
    def __init__(self, *args):
        self._tasks = args or []

    def add_task(self, coroutine):
        self._tasks.append(coroutine)
        return self

    def add_tasks(self, *args):
        self._tasks.extend(args)
        return self

    async def run(self):
        if any(self._tasks):
            return await asyncio.gather(*self._tasks)


def try_int(value):
    if value is not None:
        try:
            return int(value)
        except:
            pass
    return None


class DateUtils:
    DATE_FORMAT = '%Y-%m-%d'

    @classmethod
    def relative_delta_string(cls, delta: relativedelta):
        return f'{delta.years} year(s) {delta.months} month(s) {delta.days} day(s)'

    @classmethod
    def parse(cls, datestr):
        return parse(datestr)

    @classmethod
    def parse_timestamp(cls, datestr):
        date = parse(datestr)
        return int(date.timestamp())

    @classmethod
    def to_timestamp_day(cls, date: Union[str, datetime]):
        if date is None:
            raise Exception(f'Cannot create day timestamp from null')

        if isinstance(date, str):
            date = parse(date)

        day = cls.to_date(
            _datetime=date)

        return int(day.timestamp())

    @classmethod
    def to_date(cls, _datetime: datetime):
        return datetime(
            year=_datetime.year,
            month=_datetime.month,
            day=_datetime.day)

    @classmethod
    def to_date_string(cls, _datetime: Union[str, datetime]):
        if isinstance(_datetime, str):
            _datetime = parse(_datetime)

        return cls.to_date(
            _datetime=_datetime,
        ).strftime(cls.DATE_FORMAT)


class MongoUtils:
    @staticmethod
    def filter_range(start, end):
        return {'$lt': end, '$gte': start}


class UnitConverter:
    @staticmethod
    def inch_to_cm(inches):
        return (inches * 2.54)

    @staticmethod
    def days_old(date):
        delta = datetime.now() - date
        return round(delta.days / 365)


def get_value_map(_enum):
    return {
        v.value: k for k, v
        in _enum.__members__.items()
    }
