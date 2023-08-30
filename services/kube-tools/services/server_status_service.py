
from clients.chat_gpt_service_client import ChatGptServiceClient


class ServerStatusService:
    def __init__(
        self,
        chat_gpt_client: ChatGptServiceClient
    ):
        self.__chat_gpt_client = chat_gpt_client

    async def capture_status(
        self
    ):
        pass
