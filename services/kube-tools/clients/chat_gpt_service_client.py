from typing import Union

from clients.identity_client import IdentityClient
from domain.auth import AuthClient, ClientScope
from domain.cache import CacheKey
from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from httpx import AsyncClient

from domain.gpt import ChatGptCompletionRequest
from utilities.utils import fire_task

logger = get_logger(__name__)


class ChatGptServiceClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        identity_client: IdentityClient,
        cache_client: CacheClientAsync
    ):
        self._http_client = http_client
        self._identity_client = identity_client
        self._cache_client = cache_client

        self._base_url = configuration.chatgpt.get('base_url')

    async def get_headers(
        self
    ):
        cache_key = CacheKey.chatgpt_service_token()
        logger.info(f'Getting cached token for {cache_key}')

        token = await self._cache_client.get_cache(
            key=cache_key)

        if token is None:
            logger.info(f'No cached token found for {cache_key}')
            token = await self._identity_client.get_token(
                client_name=AuthClient.KubeToolsApi,
                scope=ClientScope.ChatGptApi)

            fire_task(
                self._cache_client.set_cache(
                    key=cache_key,
                    value=token))

        headers = {
            'Authorization': f'Bearer {token}'
        }

        logger.info(f'Headers: {headers}')

        return headers

    async def get_chat_completion(
        self,
        prompt: str
    ) -> Union[dict, int]:
        logger.info(f'Getting chat completion for prompt: {prompt}')

        headers = await self.get_headers()

        req = ChatGptCompletionRequest(prompt=prompt)

        response = await self._http_client.post(
            url=f'{self._base_url}/api/tools/chatgpt/internal/chat/completions',
            headers=headers,
            json=req.to_dict())

        logger.info(f'Response: {response.status_code}')

        return response
