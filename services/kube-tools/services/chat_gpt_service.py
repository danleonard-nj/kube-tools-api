from clients.chat_gpt_service_client import ChatGptServiceClient
from domain.exceptions import ChatGptException
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger


logger = get_logger(__name__)


class ChatGptService:
    def __init__(
        self,
        chat_gpt_client: ChatGptServiceClient
    ):
        self._chat_gpt_client = chat_gpt_client

    async def get_chat_completion(
        self,
        prompt: str
    ):
        ArgumentNullException.if_none_or_whitespace(prompt, 'prompt')

        response = await self._chat_gpt_client.get_chat_completion(
            prompt=prompt
        )

        if not response.is_success:
            raise ChatGptException(
                f'Failed to fetch internal chat completion: {response.status_code}',
                response.status_code,
                'error')

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
