import asyncio
import time
from typing import Dict

from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url
from httpx import AsyncClient

from data.chat_gpt_repository import ChatGptRepository
from domain.gpt import ChatGptHistoryRecord
from domain.rest import ChatGptHistoryEndpointsResponse, ChatGptProxyResponse
from utilities.utils import DateTimeUtil, KeyUtils

logger = get_logger(__name__)

CONTENT_TYPE = 'application/json'


class ChatGptProxyService:
    def __init__(
        self,
        configuration: Configuration,
        repository: ChatGptRepository,
        http_client: AsyncClient,
        cache_client: CacheClientAsync
    ):
        self.__http_client = http_client
        self.__repository = repository
        self.__cache_client = cache_client

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

    def __get_cache_key(
        self,
        **kwargs
    ) -> str:
        key = KeyUtils.create_uuid(
            **kwargs)

        return f'chatgpt-request-{key}'

    async def proxy_request(
        self,
        endpoint: str,
        method: str,
        request_body: dict = None,
        capture_history: bool = True
    ):
        logger.info(f'Proxy request: {method}: {endpoint}')
        headers = self.__get_headers()

        key = self.__get_cache_key(
            headers=headers,
            endpoint=endpoint,
            method=method,
            request_body=request_body)

        logger.info(f'Request key: {key}')

        cached_response = await self.__cache_client.get_json(
            key=key)

        if cached_response is not None:
            logger.info(f'Returning cached response: {key}')
            return cached_response

        # Track request time for history record
        start_time = time.time()

        response = await self.__http_client.request(
            url=f'{self.__base_url}/{endpoint}',
            method=method,
            json=request_body,
            headers=headers)

        duration = round(time.time() - start_time, 2)

        logger.info(f'Status: {response.status_code}')
        logger.info(f'Headers: {dict(response.headers)}')
        logger.info(f'Duration: {duration}s')

        result = ChatGptProxyResponse(
            request_body=request_body,
            response=response,
            duration=duration)

        # Cache the response async
        logger.info(f'Firing cache response task')
        asyncio.create_task(
            self.__cache_client.set_json(
                key=key,
                value=result.to_dict(),
                ttl=60 * 24 * 7))

        if capture_history:
            # Capture history async
            asyncio.create_task(self.capture_history(
                endpoint=endpoint,
                method=method,
                result=result))

        return result

    async def capture_history(
        self,
        endpoint: str,
        method: str,
        result: ChatGptProxyResponse
    ):
        logger.info('Storing history record')
        record = ChatGptHistoryRecord(
            endpoint=endpoint,
            method=method,
            response=result.to_dict(),
            created_date=DateTimeUtil.timestamp())

        insert_result = await self.__repository.insert(
            document=record.to_dict())
        logger.info(f'Record inserted: {insert_result.inserted_id}')

    async def get_image_generation(
        self
    ):
        pass

    async def get_usage(
        self,
        start_date,
        end_date
    ):
        end_date = (end_date or
                    DateTimeUtil.get_iso_date())

        endpoint = build_url(
            base=f'/dashboard/billing/usage',
            start_date=start_date,
            end_date=end_date
        )

        return await self.proxy_request(
            endpoint=endpoint,
            method='GET',
            capture_history=False)

    async def __get_history(
        self,
        start_timestamp: int,
        end_timestamp: int = None,
        endpoint: str = None
    ):
        end_timestamp = int(
            end_timestamp or DateTimeUtil.timestamp()
        )

        entities = await self.__repository.get_history(
            start_timestamp=int(start_timestamp),
            end_timestamp=end_timestamp,
            endpoint=endpoint)

        results = [ChatGptHistoryRecord.from_entity(entity)
                   for entity in entities]

        return results

    async def get_history(
        self,
        start_timestamp: int,
        end_timestamp: int = None,
        endpoint: str = None
    ):
        logger.info(f'Get history: {start_timestamp} - {end_timestamp}')

        return await self.__get_history(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            endpoint=endpoint)

    async def get_endpoint_history(
        self,
        start_timestamp: int,
        end_timestamp: int = None,
        endpoint=None
    ):
        logger.info(
            f'Get grouped history: {start_timestamp} - {end_timestamp}')

        end_timestamp = int(
            end_timestamp or DateTimeUtil.timestamp()
        )

        entities = await self.__repository.get_history(
            start_timestamp=int(start_timestamp),
            end_timestamp=end_timestamp,
            endpoint=endpoint)

        results = [ChatGptHistoryRecord.from_entity(entity)
                   for entity in entities]

        return ChatGptHistoryEndpointsResponse(
            results=results)
