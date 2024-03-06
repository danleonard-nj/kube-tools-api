from typing import Dict, Tuple
from click import Argument

import pandas as pd
from bs4 import BeautifulSoup
from clients.torrent_client import TorrentClient
from dateutil import parser
from domain.exceptions import InvalidTorrentSearchException
from domain.torrents import (TorrentDetail, TorrentHelper, TorrentSource,
                             format_size)
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace
from framework.exceptions.nulls import ArgumentNullException
from httpx import AsyncClient
from utilities.utils import first

logger = get_logger(__name__)


class TorrentService:
    def __init__(
        self,
        torrent_client: TorrentClient
    ):
        self._torrent_client = torrent_client

    async def search(
        self,
        target: TorrentSource,
        **kwargs
    ) -> list[TorrentDetail]:

        if none_or_whitespace(target):
            raise InvalidTorrentSearchException('No target provided')

        match target:
            case TorrentSource.L337X:
                return await self._search_1337x_torrents(
                    **kwargs)
            case TorrentSource.PirateBay:
                return await self._get_pirate_bay_torrents(
                    **kwargs)

        raise InvalidTorrentSearchException(f'Invalid target: {target}')

    async def _search_1337x_torrents(
        self,
        search_term: str,
        page: int = 1
    ):

        ArgumentNullException.if_none_or_whitespace(
            search_term, 'search_term')

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

        html = await self._torrent_client.search_torrents_1337x(
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
        data = await self._torrent_client.get_torrent_detail_1337x(
            stub=link_stub)

        magnet = TorrentHelper.parse_1337x_magnet_link(
            raw_html=data)

        return {
            'magnet': magnet
        }

    async def _get_pirate_bay_torrents(
        self,
        search_term: str,
        page
    ) -> list[TorrentDetail]:

        data = await self._torrent_client.search_torrents_tpb(
            search_term=search_term)

        return [TorrentDetail.from_pirate_bay(x) for x in data]

    async def get_magnet_link(
        self,
        target: str,
        data: Dict
    ):

        ArgumentNullException.if_none_or_whitespace(
            target, 'target')

        if target == TorrentSource.L337X:
            if 'stub' not in data:
                raise InvalidTorrentSearchException('No stub provided')
            return await self.get_1337x_magnet_link(
                link_stub=data.get('stub'))

        if target == TorrentSource.PirateBay:
            if 'info_hash' not in data:
                raise InvalidTorrentSearchException('No info hash provided')
            if 'name' not in data:
                raise InvalidTorrentSearchException('No name provided')

            magnet_link = TorrentHelper.parse_pirate_bay_magnet_link(
                name=data.get('name'),
                info_hash=data.get('info_hash'))
            return dict(magnet=magnet_link)
