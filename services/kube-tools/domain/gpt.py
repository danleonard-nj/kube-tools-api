
import os
import uuid
from typing import Dict

from framework.serialization import Serializable
from quart import Response
from utilities.utils import DateTimeUtil

DEBUG_GPT_MODEL = 'gpt-3.5-turbo'
IS_DEBUG_MODE = os.environ.get('GPT_DEBUG_MODE', '0') == '1'


class GPTModel:
    # GPT-3.5 Series
    GPT_3_5_TURBO = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-3.5-turbo"
    GPT_3_5_TURBO_0125 = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-3.5-turbo-0125"

    # GPT-4 Series
    GPT_4 = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4"
    GPT_4_0613 = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4-0613"
    GPT_4_0125_PREVIEW = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4-0125-preview"

    # GPT-4.1 Series
    GPT_4_1 = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4.1"
    GPT_4_1_MINI = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4.1-mini"
    GPT_4_1_NANO = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4.1-nano"

    # GPT-4o Series
    GPT_4O = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4o"
    GPT_4O_2024_05_13 = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4o-2024-05-13"
    GPT_4O_MINI = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-4o-mini"

    GPT_5 = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-5"
    GPT_5_MINI = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-5-mini"
    GPT_5_NANO = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-5-nano"
    GPT_5_CHAT = DEBUG_GPT_MODEL if IS_DEBUG_MODE else "gpt-5-chat"


def get_content(parsed):
    return (
        parsed
        .get('response', dict())
        .get('body', dict())
        .get('choices', list())[0]
        .get('message', dict())
        .get('content', dict())
    )


def get_usage(parsed):
    return (
        parsed
        .get('response', dict())
        .get('body', dict())
        .get('usage', dict())
        .get('total_tokens', 0)
    )


def get_error(parsed):
    return (
        parsed
        .get('response', dict())
        .get('body', dict())
        .get('error', dict())
    )


def get_internal_status(parsed):
    return (
        parsed
        .get('response', dict())
        .get('status_code', 0)
    )


class ImageSize:
    Default = '1024x1024'


class ChatGptResponse(Serializable):
    def __init__(
        self,
        body,
        status_code: int,
        headers: Dict
    ):
        self.body = body
        self.status_code = status_code
        self.headers = headers

    def json(self):
        return self.body


class ChatGptProxyResponse(Serializable):
    @property
    def request_body(self):
        return self.__request_body

    @property
    def response(self):
        return self.__response

    @property
    def duration(self):
        return self.__duration

    def __init__(
        self,
        request_body: Dict,
        response: Response,
        duration: float
    ):
        self.__request_body = request_body
        self.__response = response
        self.__duration = duration

    def to_dict(
        self
    ) -> Dict:
        return {
            'request': {
                'body': self.__request_body,
            },
            'response': {
                'body': self.__response.json(),
                'status_code': self.__response.status_code,
                'headers': dict(self.__response.headers),
            },
            'stats': {
                'duration': f'{self.__duration}s'
            }
        }

    @staticmethod
    def from_dict(data: Dict):
        return ChatGptProxyResponse(
            request_body=data.get('request').get('body'),
            response=ChatGptResponse(
                body=data.get('response').get('body'),
                status_code=data.get('response').get('status_code'),
                headers=data.get('response').get('headers')
            ),
            duration=data.get('stats').get('duration')
        )


class ChatGptHistoryEndpointsResponse(Serializable):
    def __init__(
        self,
        results: list[Dict]
    ):
        self._results = results

    def __group_results(
        self
    ):
        grouped = dict()
        for result in self._results:
            if grouped.get(result.endpoint) is None:
                grouped[result.endpoint] = []
            grouped[result.endpoint].append(result)

        return grouped

    def to_dict(self) -> Dict:
        grouped = self.__group_results()

        return {
            'endpoints': list(grouped.keys()),
            'data': grouped
        }


class ChatGptCompletionRequest(Serializable):
    def __init__(
        self,
        prompt: str
    ):
        self.prompt = prompt


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
            timestamp=DateTimeUtil.timestamp(),
            phone_number=phone_number)


class ChatGptHistoryRecord(Serializable):
    def __init__(
        self,
        history_id: str,
        endpoint: str,
        method: str,
        response: Dict,
        created_date: int
    ):
        self.history_id = history_id
        self.endpoint = endpoint
        self.method = method
        self.response = response
        self.created_date = created_date

    @staticmethod
    def from_entity(data):
        return ChatGptHistoryRecord(
            history_id=data.get('history_id'),
            endpoint=data.get('endpoint'),
            method=data.get('method'),
            response=data.get('response'),
            created_date=data.get('created_date'))

    def get_image_list(
        self
    ):
        return (self.response
                .get('response', dict())
                .get('body', dict())
                .get('data', dict()))
