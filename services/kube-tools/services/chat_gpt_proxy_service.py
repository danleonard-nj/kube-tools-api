import asyncio
import io
import time
from typing import Dict, List
import uuid
from azure.storage.blob import ContainerClient

from framework.clients.cache_client import CacheClientAsync
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url
from httpx import AsyncClient
from clients.storage_client import StorageClient

from data.chat_gpt_repository import ChatGptRepository
from domain.gpt import ChatGptHistoryRecord
from domain.rest import ChatGptHistoryEndpointsResponse, ChatGptProxyResponse, ChatGptResponse
from utilities.utils import DateTimeUtil, KeyUtils

logger = get_logger(__name__)

CONTENT_TYPE = 'application/json'
BLOB_CONTAINER_NAME = 'chatgpt-image-results'
IMAGE_ENDPOINT = '/v1/images/generations'


class ChatGptProxyService:
    def __init__(
        self,
        configuration: Configuration,
        repository: ChatGptRepository,
        http_client: AsyncClient,
        storage_client: StorageClient,
        cache_client: CacheClientAsync
    ):
        self.__http_client = http_client
        self.__repository = repository
        self.__cache_client = cache_client
        self.__storage_client = storage_client

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

    async def __capture_images(
        self,
        history_id: str,
        result: ChatGptProxyResponse
    ):
        # List of result images
        image_urls = (
            result.response
            .json()
            .get('data', [])
        )

        image_urls = [x.get('url') for x in image_urls]
        logger.info(f'Image urls: {image_urls}')

        if not any(image_urls):
            return

        async def save_image(
            url: str,
            index: int
        ):
            response = await self.__http_client.get(
                url=url)

            if response.status_code != 200:
                logger.error(f'Failed to store image: {url}')
                return

            await self.__storage_client.upload_blob(
                container_name=BLOB_CONTAINER_NAME,
                blob_name=f'{history_id}/{index}.png',
                blob_data=response.content)

        await asyncio.gather(*[
            save_image(url, index)
            for index, url in enumerate(image_urls)
        ])

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

        # Look up stored image results
        for result in results:
            if result.endpoint == IMAGE_ENDPOINT:
                image_count = result.get_image_list()
                blob_names = [f'https://stazureks.blob.core.windows.net/chatgpt-image-results/{result.history_id}/{index}.png'
                              for index in range(len(image_count))]
                result.images = blob_names

        return results

    async def proxy_request(
        self,
        endpoint: str,
        method: str,
        request_body: dict = None,
        capture_history: bool = True
    ) -> ChatGptProxyResponse:

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

            return ChatGptProxyResponse.from_dict(
                data=cached_response)

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

        gpt_response = ChatGptResponse(
            body=response.json(),
            status_code=response.status_code,
            headers=dict(response.headers)
        )

        result = ChatGptProxyResponse(
            request_body=request_body,
            response=gpt_response,
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
    ) -> str:

        logger.info('Storing history record')
        record = ChatGptHistoryRecord(
            history_id=str(uuid.uuid4()),
            endpoint=endpoint,
            method=method,
            response=result.to_dict(),
            created_date=DateTimeUtil.timestamp())

        insert_result = await self.__repository.insert(
            document=record.to_dict())
        logger.info(f'Record inserted: {insert_result.inserted_id}')

        # Store image results
        if endpoint == IMAGE_ENDPOINT:
            await self.__capture_images(
                history_id=record.history_id,
                result=result)

    async def get_usage(
        self,
        start_date,
        end_date
    ):
        logger.info(f'Get usage: {start_date} - {end_date}')

        end_date = (
            end_date or DateTimeUtil.get_iso_date()
        )

        endpoint = build_url(
            base=f'/dashboard/billing/usage',
            start_date=start_date,
            end_date=end_date
        )

        logger.info(f'Endpoint: {endpoint}')

        return await self.proxy_request(
            endpoint=endpoint,
            method='GET',
            capture_history=False)

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
