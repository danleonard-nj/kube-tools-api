import asyncio
from math import e
from typing import Dict, Tuple
from urllib.parse import quote_plus

import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser
from framework.logger import get_logger
from framework.serialization import Serializable
from framework.validators.nulls import none_or_whitespace
from httpx import AsyncClient

from clients.torrent_client import TorrentClient
from domain.torrents import TorrentDetail, TorrentSource
from quart.utils import run_sync

COLUMN_MAPPING = {
    'se': 'seeders',
    'le': 'leechers',
    'time': 'date',
    'size info': 'size',
    'link': 'stub'
}

COLUMN_CONVERTERS = {
    'time': lambda x: parser.parse(x),
}


def convert_size(value):
    segs = value.split(' ')
    bytes_value = float(segs[0])
    unit = segs[1]

    parsed_value = 0

    if unit == 'gb':
        parsed_value = bytes_value * 1024 * 1024 * 1024
    if unit == 'mb':
        parsed_value = bytes_value * 1024 * 1024
    if unit == 'kb':
        parsed_value = bytes_value * 1024
    if unit == 'b':
        parsed_value = bytes_value

    return parsed_value


def readable_size(num):
    for unit in ("", "kb", "mb", "gb", "tb", "pb"):
        if abs(num) < 1024.0:
            return f"{num:3.2f} {unit}"
        num /= 1024.0
    return f"{num:.1f}Yi"


class LinkLookupItem(Serializable):
    def __init__(
        self,
        key: str,
        link: str
    ):
        self.key = key
        self.link = link


class TorrentHelper:
    @staticmethod
    def get_1337x_link_lookup(
        soup: BeautifulSoup
    ) -> pd.DataFrame:

        logger.info(f'Parsing link lookup')
        table = soup.find_all('table')[0]

        def extract_link_data(row):
            # Get the first column
            col = row.find('td')

            # Extract the link from the column
            item = LinkLookupItem(
                key=row.text.split('\n')[1].strip(),
                link=col.find_all('a')[1].get('href'))

            return item.to_dict()

        # Parse all table tows
        data = [extract_link_data(x)
                for x in table.tbody.find_all('tr')]

        logger.info(f'Generated link lookup for {len(data)} items')

        # Create a dataframe from the lookup
        df = pd.DataFrame(data)

        return df

    @classmethod
    def format_1337x_results(
        cls,
        df: pd.DataFrame,
        soup: BeautifulSoup
    ) -> pd.DataFrame:

        link_lookup = cls.get_1337x_link_lookup(
            soup=soup)

        df = df.merge(
            right=link_lookup,
            left_on='name',
            right_on='key',
            how='left')

        logger.info(f'Formatting parsed dataframe')

        df = df.rename(columns=COLUMN_MAPPING)
        df = df[[x for x in df.columns if x != 'key']]

        return df

    @staticmethod
    def parse_1337x_magnet_link(
        raw_html: str
    ):
        mag_link = raw_html.split('magnet:')[1].split('"')[0]
        return f'magnet:{mag_link}'

    @staticmethod
    def parse_pirate_bay_magnet_link(
        name: str,
        info_hash: str
    ):
        tr = '&tr=' + quote_plus('udp://tracker.coppersurfer.tk:6969/announce')
        tr += '&tr=' + \
            quote_plus('udp://tracker.openbittorrent.com:6969/announce')
        tr += '&tr=' + quote_plus('udp://tracker.bittor.pw:1337/announce')
        tr += '&tr=' + quote_plus('udp://tracker.opentrackr.org:1337')
        tr += '&tr=' + quote_plus('udp://bt.xxx-tracker.com:2710/announce')
        tr += '&tr=' + \
            quote_plus('udp://public.popcorn-tracker.org:6969/announce')
        tr += '&tr=' + quote_plus('udp://eddie4.nl:6969/announce')
        tr += '&tr=' + quote_plus('udp://tracker.torrent.eu.org:451/announce')
        tr += '&tr=' + quote_plus('udp://p4p.arenabg.com:1337/announce')
        tr += '&tr=' + quote_plus('udp://tracker.tiny-vps.com:6969/announce')
        tr += '&tr=' + quote_plus('udp://open.stealth.si:80/announce')

        link = 'magnet:?xt=urn:btih:' + info_hash + \
            '&dn=' + quote_plus(name) + tr

        return link


def format_size(
    value
):
    try:
        segments = value.split(' ')

        unit = segments[1][:2].lower()
        size = float(segments[0].replace(',', ''))

        return f'{size} {unit}'
    except:
        return value


def first(iterable, func=None):
    for item in iterable:
        if func is None:
            return item
        else:
            if func(item) is True:
                return item


logger = get_logger(__name__)


class TorrentService:
    def __init__(
        self,
        http_client: AsyncClient,
        torrent_client: TorrentClient
    ):
        self.__http_client = http_client
        self.__torrent_client = torrent_client

    async def search(
        self,
        target: TorrentSource,
        **kwargs
    ):
        if none_or_whitespace(target):
            raise Exception('No target provided')

        match target:
            case TorrentSource.L337X:
                return await self.__search_1337x_torrents(
                    **kwargs)
            case TorrentSource.PirateBay:
                return await self.__get_pirate_bay_torrents(
                    **kwargs)

        raise Exception(f'Invalid target: {target}')

    async def __search_1337x_torrents(
        self,
        search_term: str,
        page: int = 1
    ):
        logger.info(f'Searching for: {search_term} on page: {page}')

        df, soup = await self.__get_1337x_search_results(
            search_term=search_term,
            page=page)

        logger.info(f'Found {len(df)} results')

        df = TorrentHelper.format_1337x_results(
            df=df,
            soup=soup)

        data = df.to_dict(
            orient='records')

        # Parse the 1337x data
        data = [TorrentDetail.from_1337x_to(x) for x in data]

        return data

    async def __get_1337x_search_results(
        self,
        search_term: str,
        page: int = 1
    ) -> Tuple[pd.DataFrame, BeautifulSoup]:

        html = await self.__torrent_client.search_torrents_1337x(
            search_term=search_term,
            page=page)

        # Column data converters to parse time and format size
        converters = {
            'time': lambda x: parser.parse(x),
            'size info': format_size,
        }

        logger.info(f'Parsing dataframe from response content')
        df = pd.read_html(
            html,
            converters=converters)

        df = first(df)

        logger.info(f'Parsing response content as soup')
        soup = BeautifulSoup(html, 'html.parser')

        return (
            df,
            soup
        )

    async def get_1337x_magnet_link(
        self,
        link_stub
    ):
        data = await self.__torrent_client.get_torrent_detail_1337x(
            stub=link_stub)

        magnet = TorrentHelper.parse_1337x_magnet_link(
            raw_html=data)

        return {
            'magnet': magnet
        }

    async def __get_pirate_bay_torrents(
        self,
        search_term,
        page
    ) -> list[TorrentDetail]:

        data = await self.__torrent_client.search_torrents_tpb(
            search_term=search_term)

        return [TorrentDetail.from_pirate_bay(x) for x in data]

    async def get_magnet_link(
        self,
        target,
        data: Dict
    ):
        if target == TorrentSource.L337X:
            if 'stub' not in data:
                raise Exception('No stub provided')
            return await self.get_1337x_magnet_link(
                link_stub=data.get('stub'))

        if target == TorrentSource.PirateBay:
            if 'info_hash' not in data:
                raise Exception('No info hash provided')
            if 'name' not in data:
                raise Exception('No name provided')

            magnet_link = TorrentHelper.parse_pirate_bay_magnet_link(
                name=data.get('name'),
                info_hash=data.get('info_hash'))
            return dict(magnet=magnet_link)
