from typing import Dict
from framework.configuration import Configuration
from httpx import AsyncClient
from quart import Response

CONTENT_TYPE = 'application/json'


class ChatGptProxyService:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient
    ):
        self.__http_client = http_client

        self.__base_url = configuration.chatgpt.get(
            'base_url')
        self.__auth_token = configuration.chatgpt.get(
            'auth_token')

    def __get_headers(
        self
    ) -> Dict:
        return {
            'Authorization': f'Bearer {self.__auth_token}',
            'Content-Type': CONTENT_TYPE
        }

    async def proxy_request(
        self,
        endpoint: str,
        method: str,
        request_body: dict = None
    ):
        headers = self.__get_headers()

        response = await self.__http_client.request(
            url=f'{self.__base_url}/{endpoint}',
            method=method,
            json=request_body,
            headers=headers)

        return {
            'request': {
                'body': request_body,
            },
            'response': {
                'body': response.json(),
                'status_code': response.status_code,
                'headers': dict(response.headers)
            }
        }
