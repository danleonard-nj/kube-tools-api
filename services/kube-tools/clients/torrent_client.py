from urllib.parse import quote_plus

from domain.torrents import USER_AGENT
from framework.logger import get_logger
from httpx import AsyncClient

logger = get_logger(__name__)


class TorrentClient:
    def __init__(
        self,
        http_client: AsyncClient
    ):
        self._http_client = http_client

    def _get_headers(
        self
    ):
        return {
            'User-Agent': USER_AGENT
        }

    async def search_torrents_1337x(
        self,
        search_term: str,
        page: int = 1
    ) -> str:
        parsed = quote_plus(search_term)
        logger.info(f'Parsed search term: {parsed}')

        search_url = f'https://1337x.to/search/{parsed}/{page}/'
        logger.info(f'Endpoint: {search_url}')

        response = await self._http_client.get(
            search_url,
            headers=self._get_headers())

        logger.info(f'Response status: {response.status_code}')

        return response.text

    async def search_torrents_tpb(
        self,
        search_term: str
    ):
        parsed = quote_plus(search_term)

        endpoint = f'https://apibay.org/q.php?q={parsed}&cat'
        response = await self._http_client.get(
            url=endpoint,
            headers=self._get_headers())

        data = response.json()

        return data

    async def get_torrent_detail_tpb(
        self,
        torrent_id
    ):
        endpoint = f'https://apibay.org/t.php?id={torrent_id}'
        response = await self._http_client.get(
            url=endpoint)

        data = response.json()

        return data

    async def get_torrent_detail_1337x(
        self,
        stub
    ) -> str:
        endpoint = f'https://1337x.to{stub}'
        logger.info(f'Endpoint: {endpoint}')

        data = await self._http_client.get(
            endpoint,
            headers=self._get_headers())

        logger.info(f'Response status: {data.status_code}')

        return data.text
