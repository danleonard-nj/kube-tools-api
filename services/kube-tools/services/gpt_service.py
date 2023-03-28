from datetime import datetime, timedelta
import imp
from framework.configuration import Configuration
from clients.storage_client import StorageClient
from data.gpt_job_repository import GptJobRepository
from data.gpt_user_repository import GptUserRequestRepository
from framework.crypto.hashing import sha256
from framework.logger import get_logger


from domain.gpt import GptUserRequest, ImageRequest, ImageSize, get_timestamp
from framework.exceptions.nulls import ArgumentNullException

logger = get_logger(__name__)


def get_char_count(char, string):
    count = 0
    for _char in string:
        if _char == char:
            count += 1
    return count


class InboundMessage:
    def __init__(
        self,
        text: str
    ):
        self.__text = text

    def __handle_text(self, text):
        pass


def verify_user(user: GptUserRequest):
    if not user.credits <= 10:
        raise Exception(f"User '{user.user_id}' exceeded credits")


class GptService:
    DefaultN = 4

    def __init__(
        self,
        configuration: Configuration,
        user_repo: GptUserRequestRepository,
        job_repo: GptJobRepository,
        storage_client: StorageClient
    ):
        self.__api_key = configuration.gpt.get('api_key')
        self.__user_repo = user_repo
        self.__job_repo = job_repo
        self.__storage_client = storage_client

    def __get_user_id(self):
        now = str(datetime.utcnow())
        key = sha256(str(now))
        return key[0:5]

    def is_image_reqest(self, text):
        if len(text) < 8:
            raise Exception('Invalid request type')
        if text[0:9] == 'gpt_image':
            return True
        return False

    async def handle_request(
        self,
        phone_number: str,
        text: str
    ):
        is_user_request = await self.is_key_request(
            text=text)

        if is_user_request:
            user = GptUserRequest.create_user(
                phone_number=phone_number)

            await self.__user_repo.insert(
                document=user.to_dict())

        if self.is_image_reqest(text=text):
            verified = await self.verify_user()

    async def is_key_request(
        self,
        text
    ):
        return text == 'hey'

    async def verify_user(
        self,
        user_id: str
    ):
        entity: GptUserRequest = await self.__user_repo.get({
            'user_id': user_id
        })

        if entity is None:
            raise Exception(f"No user with ID '{entity}' is known")

        if entity.credits < 10:
            raise Exception(f"You've exceeded max credits for the day!")

        expiration_seconds = timedelta(days=1).seconds
        if get_timestamp() - entity.timestamp > expiration_seconds:
            raise Exception(
                f"Your user key expired, please request a new one!")

        model = GptUserRequest.from_entity(
            data=entity)

        return model

    async def handle_prompt(
        self,
        user_id,
        prompt,
        size=None,
        n=None
    ):
        ArgumentNullException.if_none_or_whitespace(
            prompt, 'prompt')
        ArgumentNullException.if_none_or_whitespace(
            size, 'size')
        ArgumentNullException.if_none_or_whitespace(
            user_id, 'user_id')

        user: GptUserRequest = await self.__user_repo.get({
            'user_id': user_id
        })

        if user is None:
            raise Exception(f"No user with ID '{user}' is known")

        if user.credits < 10:
            raise Exception(f"You've exceeded max credits for the day!")

        expiration_seconds = timedelta(days=1).seconds
        if get_timestamp() - user.timestamp > expiration_seconds:
            raise Exception(
                f"Your user key expired, please request a new one!")

        req = ImageRequest(
            prompt=prompt,
            n=n or self.DefaultN,
            size=size or ImageSize.Default)
