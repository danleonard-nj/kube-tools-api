from typing import Dict, List

from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.logger import get_logger
from framework.uri import build_url
from framework.validators.nulls import none_or_whitespace
from httpx import AsyncClient
from google.auth.transport.requests import Request
from domain.cache import CacheKey

from domain.google import GmailEmail, GmailEmailRule, GmailQueryResult, GmailRuleAction, GoogleClientScope, GoogleEmailLabel
from domain.rest import GmailModifyEmailRequest
from services.gmail_rule_service import GmailRuleService
from services.google_auth_service import GoogleAuthService
from framework.caching.memory_cache import MemoryCache

logger = get_logger(__name__)


class GmailClient:
    def __init__(
        self,
        configuration: Configuration,
        auth_service: GoogleAuthService,
        rule_service: GmailRuleService,
        http_client: AsyncClient
    ):
        self.__auth_service = auth_service
        self.__http_client = http_client
        self.__rule_service = rule_service
        self.__memory_cache = MemoryCache()

        self.__base_url = configuration.gmail.get(
            'base_url')

    async def __get_token(
        self
    ):
        cache_key = CacheKey.gmail_token()

        token = self.__memory_cache.get(cache_key)

        if token is not None:
            return token

        client = await self.__auth_service.get_auth_client(
            scopes=GoogleClientScope.Gmail)

        logger.info(f'Client granted scopes: {client.granted_scopes}')
        logger.info(f'Client scopes: {client.scopes}')

        client.refresh(Request())

        self.__memory_cache.set(
            key=cache_key,
            value=client.token,
            ttl=60)

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
    ):
        # Build endpoint with message
        endpoint = f'{self.__base_url}/v1/users/me/messages/{message_id}'
        logger.info(f'Endpoint: {endpoint}')

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

    async def archive_message(
        self,
        message_id: str
    ):
        logger.info(f'Gmail archive message: {message_id}')

        # Build endpoint with message
        endpoint = f'{self.__base_url}/v1/users/me/messages/{message_id}/modify'
        logger.info(f'Endpoint: {endpoint}')

        remove_labels = [
            GoogleEmailLabel.Inbox,
            GoogleEmailLabel.Unread
        ]

        modify_request = GmailModifyEmailRequest(
            remove_label_ids=remove_labels)

        auth_headers = await self.__get_auth_headers()
        query_result = await self.__http_client.post(
            url=endpoint,
            json=modify_request.to_dict(),
            headers=auth_headers)

        content = query_result.json()
        return content

    async def search_inbox(
        self,
        query: str,
        page_token: str = None
    ) -> GmailQueryResult:

        logger.info(f'Gmail query: {query}')

        endpoint = build_url(
            base=f'{self.__base_url}/v1/users/me/messages',
            q=query)

        # Add continuation token if provided
        if not none_or_whitespace(page_token):
            endpoint = f'{endpoint}&pageToken={page_token}'

        logger.info(f'Endpoint: {endpoint}')

        auth_headers = await self.__get_auth_headers()
        query_result = await self.__http_client.get(
            url=endpoint,
            headers=auth_headers)

        content = query_result.json()
        response = GmailQueryResult(
            data=content)

        return response

    async def run_mail_service(
        self
    ):
        run_results = dict()
        rules = await self.__rule_service.get_rules()

        for rule in rules:
            logger.info(f'Processing rule: {rule.name}')

            # Process an archival rule
            if rule.action == GmailRuleAction.Archive:
                count = await self.process_archive_rule(
                    rule=rule)

                run_results[rule.name] = count

        return run_results

    async def process_archive_rule(
        self,
        rule: GmailEmailRule
    ) -> List[str]:

        # Query the inbox w/ the defined rule query
        query_result = await self.search_inbox(
            query=rule.query)

        logger.info(f'Result count: {len(query_result.messages)}')

        for message_id in query_result.message_ids:
            logger.info(f'Archiving email: {message_id}')

            await self.archive_message(
                message_id=message_id)

        return len(query_result.message_ids)
