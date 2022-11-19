import httpx
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url

logger = get_logger(__name__)


class ReverbClient:
    def __init__(
        self,
        configuration: Configuration
    ):
        self.__configuration = configuration
        self.__base_url = configuration.reverb.get('base_url')
        self.__api_key = configuration.reverb.get('api_key')

    def __get_headers(self):
        return {
            'accept-version': '3.0',
            'authorization': f'Bearer {self.__api_key}'
        }

    async def get_listings(
        self,
        page: int,
        items_per_page: int,
        product_type: str,
        **kwargs
    ):
        return await self.__send_request(
            uri='/listings',
            page=page,
            per_page=items_per_page,
            product_type=product_type,
            **kwargs)

    async def get_listing_detail(
        self,
        listing_bk,
        **kwargs
    ):
        return await self.__send_request(
            uri=f'/listings/{listing_bk}',
            **kwargs)

    async def get_comparison_transactions(
        self,
        slug,
        limit=100
    ):
        return await self.__send_request(
            uri=f'/csps/{slug}/transactions',
            per_page=limit)

    async def from_link(self, link):
        async with httpx.AsyncClient(timeout=None) as client:
            logger.info(f'Endpoint: {link}')

            response = await client.get(
                url=link,
                headers=self.__get_headers())

            logger.info(f'Status: {response.status_code}')
            return response.json()

    async def __send_request(
        self,
        uri,
        **kwargs
    ):
        async with httpx.AsyncClient(timeout=None) as client:
            endpoint = build_url(
                base=f'{self.__base_url}{uri}',
                **kwargs)

            logger.info(f'Endpoint: {endpoint}')

            response = await client.get(
                url=endpoint,
                headers=self.__get_headers())

            logger.info(f'Status: {response.status_code}')
            return response.json()
