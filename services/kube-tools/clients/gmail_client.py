import asyncio
import base64
from email import policy
from email.message import EmailMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.parser import BytesParser

from domain.google import (GmailEmail, GmailEmailRuleModel,
                           GmailModifyEmailRequestModel, GmailQueryResultModel,
                           GoogleClientScope, GoogleEmailHeader,
                           GoogleEmailLabel)
from framework.clients.cache_client import CacheClientAsync
from framework.concurrency import TaskCollection
from framework.concurrency.concurrency import fire_task
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.uri import build_url
from framework.validators.nulls import none_or_whitespace
from httpx import AsyncClient
from services.google_auth_service import GoogleAuthService

logger = get_logger(__name__)


class GmailClient:

    def __init__(
        self,
        configuration: Configuration,
        auth_service: GoogleAuthService,
        http_client: AsyncClient,
        cache_client: CacheClientAsync
    ):
        self._auth_service = auth_service
        self._http_client = http_client
        self._cache_client = cache_client

        self._base_url = configuration.gmail.get(
            'base_url')

        # Use 24 as default concurrency
        # concurrency = configuration.gmail.get('concurrency', 3)

        self._semaphore = asyncio.Semaphore(3)

        ArgumentNullException.if_none_or_whitespace(
            self._base_url, 'base_url')

    async def _get_token(
        self
    ) -> str:

        # Fetch an auth token w/ Gmail scope
        response = await self._auth_service.get_token(
            client_name='gmail-client',
            scopes=[GoogleClientScope.Gmail])

        return response

    async def _get_auth_headers(
        self
    ) -> dict:

        token = await self._get_token()

        return {
            'Authorization': f'Bearer {token}'
        }

    async def ensure_auth(
        self,
        scopes=list[str]
    ) -> str:
        # Fetch an auth token w/ Gmail scope

        logger.info('Assuring Gmail auth')

        response = await self._auth_service.get_token(
            client_name='gmail-client',
            scopes=scopes)

        return response

    def _get_cache_key(
        self,
        message_id: str
    ):
        return f'gmail:message:{message_id}'

    async def get_message(
        self,
        message_id: str
    ) -> GmailEmail:

        logger.debug(f'Fetching message: {message_id}')

        key = self._get_cache_key(message_id=message_id)
        cached = await self._cache_client.get_json(key)

        if cached:
            logger.debug(f'Cache hit for message: {message_id}')
            return GmailEmail(data=cached)

        # Build endpoint with message
        endpoint = f'{self._base_url}/v1/users/me/messages/{message_id}'

        auth_headers = await self._get_auth_headers()
        async with self._semaphore:

            message_response = await self._http_client.get(
                url=endpoint,
                headers=auth_headers)
            message_response.raise_for_status()

        content = message_response.json()

        # Cache the message content
        fire_task(
            self._cache_client.set_json(
                key=key,
                value=content,
                ttl=60 * 24
            )
        )

        return GmailEmail(data=content)

    async def forward_email(
        self,
        message_id: str,
        to_email: str,
        cc_emails: list[str] = None,
        subject_prefix: str = None,
        outer_content: str = 'See forwarded message.'
    ) -> dict:
        """
        Forward an email preserving the original content (attachments, inline images, formatting)
        by attaching the original message as an RFC 822 attachment. This avoids invalid header
        issues when attempting to resend the original message with modified routing headers.
        Args:
            message_id: The ID of the message to forward
            to_email: The email address to forward to
            cc_emails: Optional list of CC recipients
            subject_prefix: Optional prefix to prepend to the subject line
        Returns:
            dict: Response from Gmail API
        """

        # Step 1: Get the raw message from Gmail API (format=raw)
        endpoint = f'{self._base_url}/v1/users/me/messages/{message_id}?format=raw'
        auth_headers = await self._get_auth_headers()
        async with self._semaphore:
            message_response = await self._http_client.get(
                url=endpoint,
                headers=auth_headers)
            message_response.raise_for_status()
        message = message_response.json()
        raw_msg = message.get('raw')
        if not raw_msg:
            raise ValueError("Raw message not available in Gmail API response.")

        # Step 2: Decode base64 URL-safe message to bytes
        original_bytes = base64.urlsafe_b64decode(raw_msg.encode('utf-8'))

        # Step 3: Parse original just to extract a subject for the new wrapper message
        msg_obj = BytesParser(policy=policy.default).parsebytes(original_bytes)
        orig_subject = msg_obj['Subject'] if msg_obj['Subject'] else ''

        # Step 4: Build a new message and attach the original as message/rfc822
        outer = EmailMessage()
        outer['To'] = to_email
        # Normalize and validate CC addresses (accept str or list)
        if cc_emails:
            def _split_addrs(val: str) -> list[str]:
                # Split by comma or semicolon
                parts = []
                for sep in [',', ';']:
                    if sep in val:
                        parts = [p for chunk in val.split(sep) for p in [chunk]]
                if not parts:
                    parts = [val]
                return [p.strip() for p in parts if p and p.strip()]

            def _extract_email(token: str) -> str:
                # If format is 'Name <email@domain>' extract inside <>
                if '<' in token and '>' in token:
                    inner = token[token.find('<') + 1: token.rfind('>')].strip()
                    return inner
                return token

            if isinstance(cc_emails, str):
                cc_list = _split_addrs(cc_emails)
            else:
                cc_list = []
                for item in cc_emails:
                    if isinstance(item, str):
                        cc_list.extend(_split_addrs(item))

            # extract emails and keep those that look like addresses
            cc_clean = []
            for t in cc_list:
                if t.lower() in {'none', 'null', 'nil', 'undefined', '[]', '{}'}:
                    continue
                email_only = _extract_email(t)
                if '@' in email_only and '.' in email_only.split('@')[-1]:
                    cc_clean.append(email_only)
            if cc_clean:
                outer['Cc'] = ', '.join(cc_clean)
        if subject_prefix:
            outer['Subject'] = f"{subject_prefix}{orig_subject}"
        else:
            outer['Subject'] = orig_subject or 'Fwd:'

        # Minimal body content; clients will show the attached original
        outer.set_content(outer_content)

        # Attach original message as an RFC 822 attachment to preserve it exactly
        outer.add_attachment(
            original_bytes,
            maintype='message',
            subtype='rfc822',
            filename='forwarded.eml'
        )

        # Step 5: Encode back into base64 URL-safe for Gmail API
        forward_raw = base64.urlsafe_b64encode(outer.as_bytes()).decode('utf-8')

        # Step 6: Send the message
        send_endpoint = f'{self._base_url}/v1/users/me/messages/send'
        send_message = {'raw': forward_raw}
        auth_headers = await self._get_auth_headers()
        async with self._semaphore:
            send_response = await self._http_client.post(
                url=send_endpoint,
                json=send_message,
                headers=auth_headers
            )
            # Log useful error details before raising
            if send_response.status_code >= 400:
                try:
                    err_text = send_response.text
                except Exception:
                    err_text = '<no response text>'
                logger.error(
                    f"Failed to forward via Gmail API: {send_response.status_code} - {err_text[:2000]}"
                )
            send_response.raise_for_status()
        logger.info(f"Message forwarded (as attachment), ID: {send_response.json().get('id')}")
        return send_response.json()

    async def get_messages(
        self,
        message_ids: list[str]
    ) -> list[GmailEmail]:

        logger.debug(f'Fetching {len(message_ids)} messages')

        get_messages = TaskCollection(*[
            self.get_message(message_id=message_id)
            for message_id in message_ids
        ])

        return await get_messages.run()

    async def modify_tags(
        self,
        message_id: str,
        to_add: list[str] = [],
        to_remove: list[str] = []
    ) -> dict:

        ArgumentNullException.if_none_or_whitespace(
            message_id, 'message_id')

        cache_key = self._get_cache_key(message_id=message_id)
        logger.info(f'Invalidating cache for message: {message_id}')
        await self._cache_client.delete_key(cache_key)

        logger.info(f'Tags: add + {to_add} | remove - {to_remove}')

        # Build endpoint with message
        endpoint = f'{self._base_url}/v1/users/me/messages/{message_id}/modify'

        modify_request = GmailModifyEmailRequestModel(
            add_label_ids=to_add,
            remove_label_ids=to_remove)

        auth_headers = await self._get_auth_headers()

        async with self._semaphore:
            query_result = await self._http_client.post(
                url=endpoint,
                json=modify_request.to_dict(),
                headers=auth_headers)
            query_result.raise_for_status()

        logger.info(f'Modify tag status: {query_result.status_code}')

        content = query_result.json()
        return content

    async def archive_message(
        self,
        message_id: str
    ) -> dict:

        ArgumentNullException.if_none_or_whitespace(
            message_id, 'message_id')

        cache_key = self._get_cache_key(message_id=message_id)
        logger.info(f'Invalidating cache for message: {message_id}')
        await self._cache_client.delete_key(cache_key)

        logger.info(f'Gmail archive message: {message_id}')

        remove_labels = [
            GoogleEmailLabel.Inbox,
            GoogleEmailLabel.Unread
        ]

        async with self._semaphore:
            return await self.modify_tags(
                message_id=message_id,
                to_remove=remove_labels)

    async def search_inbox(
        self,
        query: str,
        max_results: int = None,
        page_token: str = None
    ) -> GmailQueryResultModel:

        ArgumentNullException.if_none_or_whitespace(
            query, 'query')

        # Build the inbox query endpoint
        endpoint = build_url(
            base=f'{self._base_url}/v1/users/me/messages',
            q=query)

        # Add continuation token if provided
        if not none_or_whitespace(page_token):
            endpoint = f'{endpoint}&pageToken={page_token}'

        # Add max results if provided
        if not none_or_whitespace(max_results):
            endpoint = f'{endpoint}&maxResults={max_results}'

        # Query the inbox
        auth_headers = await self._get_auth_headers()
        query_result = await self._http_client.get(
            url=endpoint,
            headers=auth_headers)

        query_result.raise_for_status()

        logger.debug(f'Query inbox result: {query_result.status_code}')

        content = query_result.json()

        if not any(content.get('messages', [])):
            logger.info(f'No results for query: {query}')
            return GmailQueryResultModel.empty_result()

        return GmailQueryResultModel.model_validate(content)
