from typing import Dict, List

from framework.caching.memory_cache import MemoryCache
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url
from framework.validators.nulls import none_or_whitespace
from google.auth.transport.requests import Request
from httpx import AsyncClient

from constants.google import GoogleEmailLabel
from domain.cache import CacheKey
from domain.google import GmailEmail, GmailQueryResult, GoogleClientScope
from domain.rest import GmailModifyEmailRequest
from services.gmail_rule_service import GmailRuleService
from services.google_auth_service import GoogleAuthService

logger = get_logger(__name__)


class GmailClient:
    def __init__(
        self,
        configuration: Configuration,
        auth_service: GoogleAuthService,
        http_client: AsyncClient
    ):
        self.__auth_service = auth_service
        self.__http_client = http_client
        self.__memory_cache = MemoryCache()

        self.__base_url = configuration.gmail.get(
            'base_url')

    async def __get_token(
        self
    ) -> str:

        cache_key = CacheKey.gmail_token()

        # Try to fetch the Gmail auth token from mem cache
        # token = self.__memory_cache.get(cache_key)
        token = None

        if token is not None:
            return token

        logger.info(f'Fetching token from auth client')

        # Fetch an auth token w/ Gmail scope
        client = await self.__auth_service.get_auth_client(
            scopes=GoogleClientScope.Gmail)

        logger.info(f'Client granted scopes: {client.granted_scopes}')
        logger.info(f'Client scopes: {client.scopes}')

        # # Fetch the token w/ refresh creds
        # client.refresh(Request())

        # Cache the fetched token
        self.__memory_cache.set(
            key=cache_key,
            value=client.token,
            ttl=60 * 45)

        logger.info(f'Client token: {client.token}')

        return client.token

    async def __get_auth_headers(
        self
    ) -> Dict:

        token = await self.__get_token()

        return {
            'Authorization': f'Bearer {token}'
        }

    async def get_message(
        self,
        message_id: str
    ) -> Dict:

        # Build endpoint with message
        endpoint = f'{self.__base_url}/v1/users/me/messages/{message_id}'

        auth_headers = await self.__get_auth_headers()
        message_response = await self.__http_client.get(
            url=endpoint,
            headers=auth_headers)

        content = message_response.json()
        return GmailEmail(
            data=content)

    async def get_messages(
        self,
        message_ids: List[str]
    ) -> List[GmailEmail]:

        logger.info(f'Fetching {len(message_ids)} messages')

        get_messages = TaskCollection(*[
            self.get_message(message_id=message_id)
            for message_id in message_ids
        ])

        return await get_messages.run()

    async def modify_tags(
        self,
        message_id: str,
        to_add: List[str] = [],
        to_remove: List[str] = []
    ) -> Dict:

        logger.info(f'Tags: add + {to_add} | remove - {to_remove}')

        # Build endpoint with message
        endpoint = f'{self.__base_url}/v1/users/me/messages/{message_id}/modify'

        modify_request = GmailModifyEmailRequest(
            add_label_ids=to_add,
            remove_label_ids=to_remove)

        auth_headers = await self.__get_auth_headers()
        query_result = await self.__http_client.post(
            url=endpoint,
            json=modify_request.to_dict(),
            headers=auth_headers)

        logger.info(f'Modify tag status: {query_result.status_code}')

        content = query_result.json()
        return content

    async def archive_message(
        self,
        message_id: str
    ):
        logger.info(f'Gmail archive message: {message_id}')

        remove_labels = [
            GoogleEmailLabel.Inbox,
            GoogleEmailLabel.Unread
        ]

        return await self.modify_tags(
            message_id=message_id,
            to_remove=remove_labels)

    async def search_inbox(
        self,
        query: str,
        max_results: int = None,
        page_token: str = None
    ) -> GmailQueryResult:

        # Build the inbox query endpoint
        endpoint = build_url(
            base=f'{self.__base_url}/v1/users/me/messages',
            q=query)

        # Add continuation token if provided
        if not none_or_whitespace(page_token):
            endpoint = f'{endpoint}&pageToken={page_token}'

        # Add max results if provided
        if not none_or_whitespace(max_results):
            endpoint = f'{endpoint}&maxResults={max_results}'

        # Query the inbox
        auth_headers = await self.__get_auth_headers()
        query_result = await self.__http_client.get(
            url=endpoint,
            headers=auth_headers)

        logger.info(f'Query inbox result: {query_result.status_code}')

        content = query_result.json()

        if content is None:
            logger.info(f'No results for query: {query}')
            return

        response = GmailQueryResult(
            data=content)
        return response
