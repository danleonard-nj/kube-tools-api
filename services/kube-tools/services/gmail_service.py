import html
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from domain.enums import ProcessGmailRuleResultType
from domain.google import (DEFAULT_PROMPT_TEMPLATE, GmailEmail, GmailEmailRule,
                           GmailRuleAction, GoogleClientScope,
                           GoogleEmailHeader, GoogleEmailLabel,
                           ProcessGmailRuleResponse, parse_gmail_body_text)
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.validators import none_or_whitespace
from services.chat_gpt_service import ChatGptService
from services.gmail_balance_sync_service import GmailBankSyncService
from services.gmail_rule_service import GmailRuleService
from utilities.utils import clean_unicode

logger = get_logger(__name__)


@dataclass
class TagModification:
    """Represents tag modifications for email messages."""
    to_add: List[GoogleEmailLabel]
    to_remove: List[GoogleEmailLabel]


class EmailTagManager:
    """Manages consistent email tag modifications."""

    @staticmethod
    def get_archive_tags() -> TagModification:
        """Tags for archiving emails."""
        return TagModification(
            to_add=[],
            to_remove=[GoogleEmailLabel.Inbox]
        )

    @staticmethod
    def get_processed_tags() -> TagModification:
        """Tags for marking emails as processed."""
        return TagModification(
            to_add=[GoogleEmailLabel.Starred],
            to_remove=[GoogleEmailLabel.Unread, GoogleEmailLabel.Inbox]
        )


class MessageFormatter:
    """Handles formatting of email messages for SMS notifications."""

    def __init__(self, chat_gpt_service: ChatGptService):
        self._chat_gpt_service = chat_gpt_service

    async def format_sms_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail
    ) -> str:
        """Format email message for SMS notification."""
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')

        # Check if ChatGPT summary is requested
        chat_gpt_summary = rule.data.get('chat_gpt_include_summary', False)

        if not chat_gpt_summary:
            return self._build_basic_message(rule, message)

        # Get ChatGPT summary
        prompt_template = rule.data.get('chat_gpt_prompt_template')
        summary = await self._get_chat_gpt_summary(message, prompt_template)

        return self._build_message_with_summary(rule, message, summary)

    def format_balance_sync_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail
    ) -> str:
        """Format email message for balance sync notifications."""
        return self._build_basic_message(rule, message)

    def _build_basic_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        summary: Optional[str] = None
    ) -> str:
        """Build the SMS message text."""
        snippet = clean_unicode(html.unescape(message.snippet)).strip()

        parts = [
            f'Rule: {rule.name}',
            f'Date: {message.timestamp}',
            ''
        ]

        if not none_or_whitespace(snippet):
            parts.extend([snippet, ''])

        if not none_or_whitespace(summary):
            parts.extend([f'GPT: {summary}', ''])

        parts.append(f'From: {message.headers[GoogleEmailHeader.From]}')

        return '\n'.join(parts)

    def _build_message_with_summary(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        summary: str
    ) -> str:
        """Build message with ChatGPT summary."""
        return self._build_basic_message(rule, message, summary)

    async def _get_chat_gpt_summary(
        self,
        message: GmailEmail,
        prompt_template: Optional[str] = None
    ) -> str:
        """Get email summary using ChatGPT."""
        logger.info('Generating ChatGPT summary for email')

        # Parse email body
        body_segments = parse_gmail_body_text(message=message)
        body_text = ' '.join(body_segments)

        # Build prompt
        if not none_or_whitespace(prompt_template):
            logger.info(f'Using custom prompt template: {prompt_template}')
            prompt = f"{prompt_template}: {body_text}"
        else:
            prompt = f"{DEFAULT_PROMPT_TEMPLATE}: {body_text}"

        # Get summary from ChatGPT
        result, usage = await self._chat_gpt_service.get_chat_completion(prompt=prompt)

        logger.info(f'ChatGPT email summary usage tokens: {usage}')
        return result


class BaseRuleProcessor(ABC):
    """Base class for rule processors with common functionality."""

    def __init__(
        self,
        gmail_client: GmailClient,
        message_formatter: MessageFormatter
    ):
        self._gmail_client = gmail_client
        self._message_formatter = message_formatter

    async def process_rule(self, rule: GmailEmailRule) -> int:
        """Process a rule and return the number of affected emails."""
        ArgumentNullException.if_none(rule, 'rule')

        logger.info(f'Processing {self.get_processor_name()} rule: {rule.name}')

        # Query inbox with rule query
        query_result = await self._gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results
        )

        if query_result is None or not query_result.message_ids:
            logger.info(f'No emails found for rule: {rule.name}')
            return 0

        logger.info(f'Query result count: {query_result.count}')
        processed_count = 0

        for message_id in query_result.message_ids:
            try:
                message = await self._gmail_client.get_message(message_id=message_id)

                if not self._should_process_message(message):
                    continue

                logger.info(f'Processing message {message_id} for rule: {rule.name}')

                # Process the specific message
                await self._process_message(rule, message, message_id)

                # Apply tag modifications
                tag_modification = self._get_tag_modification()
                if tag_modification:
                    await self._apply_tag_modification(message_id, tag_modification)

                processed_count += 1

            except Exception as ex:
                logger.exception(f'Failed to process message {message_id}: {str(ex)}')
                # Continue processing other messages

        return processed_count

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Determine if a message should be processed."""
        # Default implementation - can be overridden by subclasses
        return True

    async def _apply_tag_modification(
        self,
        message_id: str,
        tag_modification: TagModification
    ) -> None:
        """Apply tag modifications to a message."""
        if tag_modification.to_add or tag_modification.to_remove:
            await self._gmail_client.modify_tags(
                message_id=message_id,
                to_add=tag_modification.to_add,
                to_remove=tag_modification.to_remove
            )
            logger.info(f'Tags applied - Add: {tag_modification.to_add}, Remove: {tag_modification.to_remove}')

    @abstractmethod
    async def _process_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Process a specific message according to rule logic."""
        pass

    @abstractmethod
    def _get_tag_modification(self) -> Optional[TagModification]:
        """Get the tag modification for this processor type."""
        pass

    @abstractmethod
    def get_processor_name(self) -> str:
        """Get the name of this processor for logging."""
        pass


class ArchiveRuleProcessor(BaseRuleProcessor):
    """Processes archive rules."""

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Only process messages that are still in inbox."""
        return GoogleEmailLabel.Inbox in message.label_ids

    async def _process_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Archive the message."""
        await self._gmail_client.archive_message(message_id=message_id)
        logger.info(f'Archived email: {message_id}')

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Archive rules don't need additional tag modifications."""
        return None

    def get_processor_name(self) -> str:
        return "archive"


class SmsRuleProcessor(BaseRuleProcessor):
    """Processes SMS notification rules."""

    def __init__(
        self,
        gmail_client: GmailClient,
        message_formatter: MessageFormatter,
        twilio_gateway: TwilioGatewayClient,
        sms_recipient: str
    ):
        super().__init__(gmail_client, message_formatter)
        self._twilio_gateway = twilio_gateway
        self._sms_recipient = sms_recipient

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Only process unread messages."""
        return GoogleEmailLabel.Unread in message.label_ids

    async def _process_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Send SMS notification for the message."""
        message_body = await self._message_formatter.format_sms_message(rule, message)

        logger.info(f'Sending SMS notification for message: {message_id}')
        await self._twilio_gateway.send_sms(
            recipient=self._sms_recipient,
            message=message_body
        )

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Mark as processed and remove from inbox."""
        return EmailTagManager.get_processed_tags()

    def get_processor_name(self) -> str:
        return "SMS"


class BankSyncRuleProcessor(BaseRuleProcessor):
    """Processes bank sync rules."""

    def __init__(
        self,
        gmail_client: GmailClient,
        message_formatter: MessageFormatter,
        bank_sync_service: GmailBankSyncService,
        twilio_gateway: TwilioGatewayClient,
        sms_recipient: str
    ):
        super().__init__(gmail_client, message_formatter)
        self._bank_sync_service = bank_sync_service
        self._twilio_gateway = twilio_gateway
        self._sms_recipient = sms_recipient

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Only process unread messages."""
        return GoogleEmailLabel.Unread in message.label_ids

    async def _process_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Process bank sync for the message."""
        # Get bank sync configuration
        bank_key = rule.data.get('bank_sync_bank_key')
        alert_type = rule.data.get('bank_sync_alert_type')

        if none_or_whitespace(bank_key):
            raise GmailServiceError(
                f'Bank key not defined for bank sync rule: {rule.name}'
            )

        logger.info(f'Processing bank sync with bank key: {bank_key}')

        # Handle balance sync
        await self._bank_sync_service.handle_balance_sync(
            rule=rule,
            message=message,
            bank_key=bank_key
        )

        # Send alert if configured
        try:
            await self._send_balance_sync_alert(rule, message, alert_type)
        except Exception as ex:
            logger.exception(f'Failed to send balance sync alert: {str(ex)}')

    async def _send_balance_sync_alert(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        alert_type: str = 'none'
    ) -> None:
        """Send balance sync alert."""
        if alert_type == GmailRuleAction.Undefined:
            logger.info(f'No alert type defined for bank sync rule: {rule.name}')
            return

        if alert_type == GmailRuleAction.SMS:
            logger.info('Sending SMS alert for bank sync')
            message_body = self._message_formatter.format_balance_sync_message(rule, message)

            await self._twilio_gateway.send_sms(
                recipient=self._sms_recipient,
                message=message_body
            )
        else:
            raise GmailServiceError(
                f"Balance sync alert type '{alert_type}' is not currently supported"
            )

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Mark as processed and remove from inbox."""
        return EmailTagManager.get_processed_tags()

    def get_processor_name(self) -> str:
        return "bank sync"


class GmailServiceError(Exception):
    pass


class GmailService:
    def __init__(
        self,
        configuration: Configuration,
        gmail_client: GmailClient,
        rule_service: GmailRuleService,
        bank_sync_service: GmailBankSyncService,
        twilio_gateway: TwilioGatewayClient,
        chat_gpt_service: ChatGptService
    ):
        self._gmail_client = gmail_client
        self._rule_service = rule_service
        self._twilio_gateway = twilio_gateway
        self._bank_sync_service = bank_sync_service
        self._chat_gpt_service = chat_gpt_service

        self._sms_recipient = configuration.gmail.get(
            'sms_recipient')

    async def run_mail_service(
        self
    ) -> Dict[str, int]:

        logger.info(f'Gathering rules for Gmail rule service')

        rules = await self._rule_service.get_rules()

        if not any(rules):
            logger.info(f'No rules found to process')
            return []

        rules.reverse()

        logger.info(f'Rules gathered: {len(rules)}')

        # Ensure the client is authenticated before processing to
        # prevent multiple threads from attempting to authenticate
        # at the same time
        await self._gmail_client.ensure_auth(
            scopes=[GoogleClientScope.Gmail])

        # Process the rules asynchronously
        process_rules = TaskCollection(*[
            self.process_rule(rule=rule)
            for rule in rules
        ])

        results = await process_rules.run()

        results.sort(key=lambda x: x.rule_name)

        return results

    async def process_rule(
        self,
        rule: GmailEmailRule
    ):
        ArgumentNullException.if_none(rule, 'process_request')

        try:
            logger.info(f'Processing rule: {rule.rule_id}: {rule.name}')

            # Process the rule based on its action
            affected_count = 0

            match rule.action:
                case GmailRuleAction.Archive:
                    affected_count = await self.process_archive_rule(rule=rule)

                case GmailRuleAction.SMS:
                    affected_count = await self.process_sms_rule(rule=rule)

                case GmailRuleAction.BankSync:
                    affected_count = await self.process_bank_sync_rule(rule=rule)

                case _:
                    raise GmailServiceError(
                        f'Unsupported rule action: {rule.action}')

            logger.info(
                f'Rule: {rule.name}: Emails affected: {affected_count}')

            return ProcessGmailRuleResponse(
                status=ProcessGmailRuleResultType.Success,
                rule=rule,
                affected_count=affected_count)

        except Exception as ex:
            logger.exception(
                f'Failed to process rule: {rule.rule_id}: {rule.name}: {str(ex)}')

            return ProcessGmailRuleResponse(
                status=ProcessGmailRuleResultType.Failure,
                rule=rule)

    async def process_archive_rule(
        self,
        rule: GmailEmailRule
    ) -> List[str]:

        ArgumentNullException.if_none(rule, 'rule')

        # Query the inbox w/ the defined rule query
        query_result = await self._gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        archive_count = 0

        if query_result is None:
            logger.info(f'No emails found for rule: {rule.name}')
            return archive_count

        logger.info(f'Result count: {query_result.count}')
        for message_id in query_result.message_ids:
            message = await self._gmail_client.get_message(
                message_id=message_id)

            # If the inbox label isn't present then the email
            # is already archived and can be skipped
            if GoogleEmailLabel.Inbox not in message.label_ids:
                continue

            logger.info(f'Rule: {rule.name}: Archiving email: {message_id}')

            await self._gmail_client.archive_message(
                message_id=message_id)

            archive_count += 1

        return archive_count

    async def process_bank_sync_rule(
        self,
        rule: GmailEmailRule
    ):
        ArgumentNullException.if_none(rule, 'rule')

        logger.info(f'Processing bank sync rule: {rule.name}')

        # Query the inbox w/ the defined rule query
        query_result = await self._gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Query result count: {query_result.count}')
        sync_count = 0

        for message_id in query_result.message_ids:
            logger.debug(f'Get email message: {message_id}')

            message = await self._gmail_client.get_message(
                message_id=message_id)

            # If the email is read, ignore it
            if GoogleEmailLabel.Unread not in message.label_ids:
                continue

            logger.info(f'Message eligible for bank sync: {message_id}')

            # Mapped bank sync config data for the email rule
            bank_key = rule.data.get('bank_sync_bank_key')
            alert_type = rule.data.get('bank_sync_alert_type')

            logger.info(f'Mapped bank key: {bank_key}')

            if none_or_whitespace(bank_key):
                raise GmailServiceError(
                    f'Bank key not defined for bank sync rule: {rule.name}')

            await self._bank_sync_service.handle_balance_sync(
                rule=rule,
                message=message,
                bank_key=bank_key)

            # Mark read so we dont process this email again
            to_add = [GoogleEmailLabel.Starred]

            to_remove = [GoogleEmailLabel.Unread,
                         GoogleEmailLabel.Inbox]

            await self._gmail_client.modify_tags(
                message_id=message_id,
                to_add=to_add,
                to_remove=to_remove)

            logger.info(f'Tags add/remove: {to_add}: {to_remove}')

            try:
                await self._send_balance_sync_alert(
                    rule=rule,
                    message=message,
                    alert_type=alert_type)
            except Exception as e:
                logger.exception(f'Failed to send balance sync alert: {str(e)}')

            sync_count += 1

        return sync_count

    async def _send_balance_sync_alert(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        alert_type: str = 'none'
    ):
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')
        ArgumentNullException.if_none_or_whitespace(alert_type, 'alert_type')

        if alert_type == GmailRuleAction.Undefined:
            logger.info(f'No alert type defined for bank sync rule: {rule.name}')
            return

        body = self._get_sms_message_text(
            rule=rule,
            message=message)

        logger.info(f'Message body: {body}')

        # Currently the only notifications supported are SMS
        if alert_type == GmailRuleAction.SMS:
            logger.info(f'Sending SMS alert for bank sync')

            # Send the email snippet in the message body
            await self._twilio_gateway.send_sms(
                recipient=self._sms_recipient,
                message=body)

        else:
            raise GmailServiceError(
                f"Balance sync alert type '{alert_type}' is not currently supported")

    async def process_sms_rule(
        self,
        rule: GmailEmailRule
    ):
        ArgumentNullException.if_none(rule, 'rule')

        logger.info(f'Processing SMS rule: {rule.name}')

        # Query the inbox w/ the defined rule query
        query_result = await self._gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Query result count: {query_result.count}')
        notify_count = 0

        for message_id in query_result.message_ids:
            message = await self._gmail_client.get_message(
                message_id=message_id)

            # If the email is read, ignore it
            if GoogleEmailLabel.Unread not in message.label_ids:
                continue

            logger.info(f'Message eligible for notification: {message_id}')

            body = await self._get_sms_message_body(
                message=message,
                rule=rule)

            logger.info(f'Message body: {body}')

            # Send the email snippet in the message body
            await self._twilio_gateway.send_sms(
                recipient=self._sms_recipient,
                message=body)

            # Mark read the email so another notification isn't sent
            to_add = [GoogleEmailLabel.Starred]

            to_remove = [GoogleEmailLabel.Unread,
                         GoogleEmailLabel.Inbox]

            await self._gmail_client.modify_tags(
                message_id=message_id,
                to_add=to_add,
                to_remove=to_remove)

            logger.info(f'Tags add/remove: {to_add}: {to_remove}')

            notify_count += 1

        return notify_count

    async def _get_sms_message_body(
        self,
        message: GmailEmail,
        rule: GmailEmailRule
    ):
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')

        # TODO: Define class for additional rule config data
        chat_gpt_summary = rule.data.get('chat_gpt_include_summary', False)

        if not chat_gpt_summary:
            return self._get_sms_message_text(
                rule=rule,
                message=message)

        # Get the custom prompt template if provided
        prompt_template = rule.data.get('chat_gpt_prompt_template')

        # Get the email summary using ChatGPT
        summary = await self._get_chat_gpt_email_summary(
            message=message,
            prompt_template=prompt_template)

        return self._get_sms_message_text(
            rule=rule,
            message=message,
            summary=summary)

    async def _get_chat_gpt_email_summary(
        self,
        message: GmailEmail,
        prompt_template: str = None
    ):
        logger.info(f'Parsing email body')

        # Parse the email body segments
        body = parse_gmail_body_text(
            message=message)

        # Generate a prompt to summarize the email
        prompt = f"{DEFAULT_PROMPT_TEMPLATE}: {' '.join(body)}"

        # Use custom prompt template if provided
        if not none_or_whitespace(prompt_template):
            logger.info(f'Using custom prompt template: {prompt_template}')
            prompt = f"{prompt_template}: {' '.join(body)}"

        # Get the email summary from ChatGPT service
        result, usage = await self._chat_gpt_service.get_chat_completion(
            prompt=prompt)

        logger.info(f'ChatGPT email summary usage tokens: {usage}')

        return result

    def _get_sms_message_text(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        summary: str = None
    ):
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')

        snippet = clean_unicode(
            html.unescape(message.snippet)).strip()

        body = f'Rule: {rule.name}'
        body += '\n'
        body += f'Date: {message.timestamp}'
        body += '\n'
        body += '\n'

        if not none_or_whitespace(snippet):
            body += snippet
            body += '\n'
            body += '\n'

        if not none_or_whitespace(summary):
            body += f'GPT: {summary}'
            body += '\n'
            body += '\n'

        body += f'From: {message.headers[GoogleEmailHeader.From]}'

        # body += '\n'
        # body += f'{GMAIL_MESSAGE_URL}/{message.message_id}'

        return body
