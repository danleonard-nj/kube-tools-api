from typing import Tuple
from urllib.parse import quote_plus

import pandas as pd
from bs4 import BeautifulSoup
from dateutil import parser
from framework.logger import get_logger
from httpx import AsyncClient


USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'

COLUMN_MAPPING = {
    'se': 'seeders',
    'le': 'leechers',
    'time': 'date',
    'size info': 'size',
    'link': 'stub'
}


def format_size(
    value
):
    segments = value.split(' ')

    unit = segments[1][:2].lower()
    size = float(segments[0])

    return f'{size} {unit}'


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
        http_client: AsyncClient
    ):
        self.__http_client = http_client

    async def search(
        self,
        search_term: str,
        page: int = 1
    ):
        logger.info(f'Searching for: {search_term} on page: {page}')

        df, soup = await self.__get_search_results(
            search_term=search_term,
            page=page)

        logger.info(f'Found {len(df)} results')

        link_lookup = self.__get_link_lookup(
            soup=soup)

        df = df.merge(
            right=link_lookup,
            left_on='name',
            right_on='key',
            how='left')

        logger.info(f'Formatting parsed dataframe')

        df = df.rename(columns=COLUMN_MAPPING)
        df = df[[x for x in df.columns if x != 'key']]

        data = df.to_dict(
            orient='records')

        return data

    async def __get_search_results(
        self,
        search_term: str,
        page: int = 1
    ) -> Tuple[pd.DataFrame, BeautifulSoup]:

        parsed = quote_plus(search_term)
        logger.info(f'Parsed search term: {parsed}')

        search_url = f'https://1337x.to/search/{parsed}/{page}/'
        logger.info(f'Endpoint: {search_url}')

        response = await self.__http_client.get(
            search_url,
            headers={
                'User-Agent': USER_AGENT
            })

        logger.info(f'Response status: {response.status_code}')

        # Column data converters to parse time and format size
        converters = {
            'time': lambda x: parser.parse(x),
            'size info': format_size,
        }

        logger.info(f'Parsing dataframe from response content')
        df = pd.read_html(
            response.text,
            converters=converters)

        df = first(df)

        logger.info(f'Parsing response content as soup')
        soup = BeautifulSoup(response.text, 'html.parser')

        return (
            df,
            soup
        )

    def __get_link_lookup(
        self,
        soup: BeautifulSoup
    ) -> pd.DataFrame:

        logger.info(f'Parsing link lookup')
        table = soup.find_all('table')[0]

        data = list()

        for row in table.tbody.find_all('tr'):
            col = row.find('td')

            link = col.find_all('a')[1]
            name = row.text.split('\n')[1].strip()

            data.append({
                'key': name,
                'link': link.get('href')
            })

        logger.info(f'Generated link lookup for {len(data)} items')

        return pd.DataFrame(data)

    def parse_mag_link(
        self,
        raw_html: str
    ):
        mag_link = raw_html.split('magnet:')[1].split('"')[0]
        return f'magnet:{mag_link}'

    async def get_magnet_link(
        self,
        link_stub
    ):
        endpoint = f'https://1337x.to{link_stub}'
        logger.info(f'Endpoint: {endpoint}')

        data = await self.__http_client.get(
            endpoint,
            headers={
                'User-Agent': USER_AGENT
            })

        logger.info(f'Response status: {data.status_code}')

        magnet = self.parse_mag_link(
            data.text)

        return {
            'magnet': magnet
        }
