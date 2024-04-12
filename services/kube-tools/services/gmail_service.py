import html
from typing import Dict, List

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from domain.enums import ProcessGmailRuleResultType
from domain.exceptions import GmailRuleProcessingException
from domain.google import (DEFAULT_PROMPT_TEMPLATE, GmailEmail, GmailEmailRule,
                           GmailRuleAction, GoogleClientScope,
                           GoogleEmailHeader, GoogleEmailLabel,
                           ProcessGmailRuleResponse, parse_gmail_body_text)
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.validators.nulls import none_or_whitespace
from services.chat_gpt_service import ChatGptService
from services.gmail_balance_sync_service import GmailBankSyncService
from services.gmail_rule_service import GmailRuleService
from utilities.utils import clean_unicode

logger = get_logger(__name__)


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
            scopes=GoogleClientScope.Gmail)

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
                    raise GmailRuleProcessingException(
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
                raise GmailRuleProcessingException(
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
            raise GmailRuleProcessingException(
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

        body += snippet
        body += '\n'
        body += '\n'

        if summary:
            body += f'GPT: {summary}'
            body += '\n'
            body += '\n'

        body += f'From: {message.headers[GoogleEmailHeader.From]}'

        # body += '\n'
        # body += f'{GMAIL_MESSAGE_URL}/{message.message_id}'

        return body
