import enum
from datetime import datetime
from urllib.parse import quote_plus

import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser
from framework.serialization import Serializable
from utilities.utils import ValueConverter

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'

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


class TorrentSource(enum.StrEnum):
    PirateBay = 'piratebay'
    L337X = '1337x'


class TorrentDetail(Serializable):
    def __init__(
        self,
        name,
        seeders,
        leechers,
        date,
        size,
        uploader,
        source,
        data=None
    ):
        self.name = name
        self.seeders = seeders
        self.leechers = leechers
        self.date = date
        self.size = size
        self.uploader = uploader
        self.source = source
        self.data = data

    @staticmethod
    def from_pirate_bay(data):
        created_date = datetime.fromtimestamp(
            int(data.get('added')))

        size = ValueConverter.bytes_to_megabytes(
            bytes=int(data.get('size') or 0))

        additional_data = {
            'info_hash': data.get('info_hash'),
            'imdb': data.get('imdb'),
            'id': data.get('id'),
            'name': data.get('name')
        }

        return TorrentDetail(
            name=data.get('name'),
            seeders=data.get('seeders'),
            leechers=data.get('leechers'),
            size=f'{size} mb',
            uploader=data.get('username'),
            date=created_date,
            source=TorrentSource.PirateBay,
            data=additional_data)

    @staticmethod
    def from_1337x_to(data):
        additional_data = {
            'stub': data.get('stub')
        }

        return TorrentDetail(
            name=data.get('name'),
            seeders=data.get('seeders'),
            leechers=data.get('leechers'),
            size=data.get('size'),
            uploader=data.get('uploader'),
            date=data.get('date'),
            data=additional_data,
            source=TorrentSource.L337X)


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
