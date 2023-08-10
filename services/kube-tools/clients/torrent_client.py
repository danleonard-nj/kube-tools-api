from framework.logger import get_logger
from urllib.parse import quote_plus
from httpx import AsyncClient

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36'

logger = get_logger(__name__)


class TorrentClient:
    def __init__(
        self,
        http_client: AsyncClient
    ):
        self.__http_client = http_client

    def __get_headers(
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

        response = await self.__http_client.get(
            search_url,
            headers=self.__get_headers())

        logger.info(f'Response status: {response.status_code}')

        return response.text

    async def search_torrents_tpb(
        self,
        search_term: str
    ):
        parsed = quote_plus(search_term)

        endpoint = f'https://apibay.org/q.php?q={parsed}&cat'
        response = await self.__http_client.get(
            url=endpoint,
            headers=self.__get_headers())

        data = response.json()

        return data

    async def get_torrent_detail_tpb(
        self,
        torrent_id
    ):
        endpoint = f'https://apibay.org/t.php?id={torrent_id}'
        response = await self.__http_client.get(
            url=endpoint)

        data = response.json()

        return data

    async def get_torrent_detail_1337x(
        self,
        stub
    ) -> str:
        endpoint = f'https://1337x.to{stub}'
        logger.info(f'Endpoint: {endpoint}')

        data = await self.__http_client.get(
            endpoint,
            headers=self.__get_headers())

        logger.info(f'Response status: {data.status_code}')

        return data.text
