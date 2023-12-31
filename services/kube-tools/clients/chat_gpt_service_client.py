import asyncio

from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from httpx import AsyncClient

from clients.identity_client import IdentityClient
from domain.auth import ClientScope
from domain.cache import CacheKey
from domain.exceptions import ChatGptException
from domain.rest import ChatGptCompletionRequest

logger = get_logger(__name__)


class ChatGptServiceClient:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        identity_client: IdentityClient,
        cache_client: CacheClientAsync
    ):
        self.__http_client = http_client
        self.__identity_client = identity_client
        self.__cache_client = cache_client

        self.__base_url = configuration.chatgpt.get('base_url')

    async def get_headers(
        self
    ):
        cache_key = CacheKey.chatgpt_service_token()
        logger.info(f'Getting cached token for {cache_key}')

        token = await self.__cache_client.get_cache(
            key=cache_key)

        if token is None:
            logger.info(f'No cached token found for {cache_key}')
            token = await self.__identity_client.get_token(
                client_name='kube-tools-api',
                scope=ClientScope.ChatGptApi)

            asyncio.create_task(
                self.__cache_client.set_cache(
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
    ):
        logger.info(f'Getting chat completion for prompt: {prompt}')

        headers = await self.get_headers()

        req = ChatGptCompletionRequest(prompt=prompt)

        response = await self.__http_client.post(
            url=f'{self.__base_url}/api/tools/chatgpt/internal/chat/completions',
            headers=headers,
            json=req.to_dict())

        logger.info(f'Response: {response.status_code}')

        if not response.is_success:
            raise ChatGptException(
                f'Failed to fetch internal chat completion: {response.status_code}')

        parsed = response.json()

        internal_status = (
            parsed
            .get('response', dict())
            .get('status_code', 0)
        )

        if internal_status != 200:
            error = (
                parsed
                .get('response', dict())
                .get('body', dict())
                .get('error', dict())
            )

            if internal_status == 429:
                raise ChatGptException(
                    message=f'Internal chatgpt service is rate limited: {internal_status}',
                    status_code=internal_status,
                    gpt_error=error)

            if internal_status == 503:
                raise ChatGptException(
                    f'Internal chatgpt service is unavailable: {internal_status}',
                    status_code=internal_status,
                    gpt_error=error)

        result = (
            parsed
            .get('response', dict())
            .get('body', dict())
            .get('choices', list())[0]
            .get('message', dict())
            .get('content', dict())
        )

        usage = (
            parsed
            .get('response', dict())
            .get('body', dict())
            .get('usage', dict())
            .get('total_tokens', 0)
        )

        logger.info(f'Result: {result}')
        logger.info(f'Usage: {usage} token(s)')

        return result, usage
