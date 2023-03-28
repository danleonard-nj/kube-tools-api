
import uuid
from datetime import datetime
from framework.serialization import Serializable


def get_timestamp() -> int:
    return int(
        datetime.now().timestamp())


class ImageSize:
    Default = '1024x1024'


class ImageRequest(Serializable):
    def __init__(
        self,
        prompt: str,
        n: int,
        size: str = ImageSize.Default
    ):
        self.prompt = prompt
        self.n = n
        self.size = size


class GptUserRequest(Serializable):
    def __init__(
        self,
        user_id: str,
        phone_number: str,
        timestamp: int,
        request_count: int = 0,
        credits: int = 0,
        last_modified: int = 0
    ):
        self.user_id = user_id
        self.phone_number = phone_number
        self.timestamp = timestamp
        self.request_count = request_count
        self.credits = credits
        self.last_modified = last_modified

    @staticmethod
    def from_entity(data):
        return GptUserRequest(
            user_id=data.get('user_id'),
            phone_number=data.get('phone_number'),
            timestamp=data.get('timestamp'),
            request_count=data.get('request_count'),
            credits=data.get('credits'),
            last_modified=data.get('last_modified'))

    @staticmethod
    def create_user(phone_number):
        return GptUserRequest(
            user_id=str(uuid.uuid4()),
            timestamp=get_timestamp(),
            phone_number=phone_number)
