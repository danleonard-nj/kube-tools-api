from typing import Dict
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from httpx import AsyncClient
from framework.logger import get_logger

from domain.gpt import ImageRequest

logger = get_logger(__name__)


class GptClient:
    def __init__(
            self,
            http_client: AsyncClient,
            configuration: Configuration):

        self.__base_url = configuration.gpt.get('base_url')
        self.__bearer = configuration.gpt.get('bearer')

        self.__http_client = http_client

    def get_headers(
        self
    ):
        return {
            'Authorization': f'Bearer {self.__bearer}'
        }

    async def create_image_request(
        self,
        req: ImageRequest
    ) -> Dict:

        ArgumentNullException.if_none(req, 'req')

        endpoint = f'{self.__base_url}/images/generations'
        logger.info(f'Endpoint: {endpoint}')

        logger.info(f'Request: {req.to_dict()}')

        res = await self.__http_client.post(
            url=endpoint,
            json=req.to_dict())

        return res.json()
