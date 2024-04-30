from clients.chat_gpt_service_client import ChatGptServiceClient
from domain.gpt import get_content, get_error, get_internal_status, get_usage
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

logger = get_logger(__name__)


class ChatGptServiceException(Exception):
    retryable_status_codes = [429, 503]

    def __init__(self, message, status_code=0, gpt_error='error', *args: object) -> None:
        self.status_code = status_code
        self.gpt_error = gpt_error
        self.message = message
        self.retry = status_code in self.retryable_status_codes

        super().__init__(message)


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

        # Fetch a chat completion from the ChatGPT gateway service
        response = await self._chat_gpt_client.get_chat_completion(
            prompt=prompt)

        if not response.is_success:
            raise ChatGptServiceException(
                message=f'Failed to fetch chat completion: {response.status_code}',
                status_code=response.status_code)

        parsed = response.json()

        internal_status = get_internal_status(parsed)

        if internal_status == 429:
            raise ChatGptServiceException(
                message=f'Internal ChatGPT proxy service is rate limited: {internal_status}',
                status_code=internal_status,
                gpt_error=get_error(parsed))

        if internal_status == 503:
            raise ChatGptServiceException(
                message=f'Internal ChatGPT proxy service is unavailable: {internal_status}',
                status_code=internal_status,
                gpt_error=get_error(parsed))

        return (
            get_content(parsed), get_usage(parsed)
        )
