from typing import Dict, List

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from domain.bank import BankRuleConfiguration
from domain.enums import ProcessGmailRuleResultType
from domain.exceptions import GmailRuleProcessingException
from domain.google import (GmailEmail, GmailEmailRule, GmailRuleAction,
                           GoogleClientScope, GoogleEmailLabel,
                           ProcessGmailRuleResponse)
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from services.gmail_balance_sync_service import GmailBankSyncService
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)


class GmailService:
    def __init__(
        self,
        configuration: Configuration,
        gmail_client: GmailClient,
        rule_service: GmailRuleService,
        bank_sync_service: GmailBankSyncService,
        twilio_gateway: TwilioGatewayClient
    ):
        self._gmail_client = gmail_client
        self._rule_service = rule_service
        self._twilio_gateway = twilio_gateway
        self._bank_sync_service = bank_sync_service

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

        archived = 0

        if query_result is None:
            logger.info(f'No emails found for rule: {rule.name}')
            return archived

        logger.info(f'Result count: {len(query_result.messages or [])}')
        for message_id in query_result.message_ids:
            message = await self._gmail_client.get_message(
                message_id=message_id)

            # If the inbox label isn't present then the email
            # is already archived and can be skipped
            if GoogleEmailLabel.Inbox not in message.label_ids:
                continue

            logger.info(f'Rule: {rule.name}: Archiving email: {message_id}')

            archived += 1
            await self._gmail_client.archive_message(
                message_id=message_id)

        return archived

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

        logger.info(f'Query result count: {len(query_result.messages)}')
        notify_count = 0

        for message_id in query_result.message_ids:
            logger.debug(f'Get email message: {message_id}')

            message = await self._gmail_client.get_message(
                message_id=message_id)

            # If the email is read, ignore it
            if GoogleEmailLabel.Unread not in message.label_ids:
                continue

            logger.info(f'Message eligible for bank sync: {message_id}')

            bank_rule_config = await self._bank_sync_service.handle_balance_sync(
                rule=rule,
                message=message)

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
                await self.send_balance_sync_alert(
                    rule=rule,
                    message=message,
                    bank_rule_config=bank_rule_config)
            except Exception as e:
                logger.exception(
                    f'Failed to send balance sync alert: {str(e)}')

            notify_count += 1

        return notify_count

    async def send_balance_sync_alert(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        bank_rule_config: BankRuleConfiguration,
    ):
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')
        ArgumentNullException.if_none(bank_rule_config, 'bank_rule_config')

        # Send a normal alert if configured in addition
        # to syncing the balance
        if (bank_rule_config is None
                or bank_rule_config.alert_type is None):
            logger.info(
                f'No bank rule config found: {rule.name}')
            return

        if bank_rule_config.alert_type == GmailRuleAction.Undefined:
            logger.info(
                f'No alert type set for bank sync: {bank_rule_config.bank_key}')
            return

        body = self._get_message_body(
            rule=rule,
            message=message)

        logger.info(f'Message body: {body}')

        # Currently the only notifications supported are SMS
        if bank_rule_config.alert_type == GmailRuleAction.SMS:
            logger.info(f'Sending SMS alert for bank sync')

            # Send the email snippet in the message body
            await self._twilio_gateway.send_sms(
                recipient=self._sms_recipient,
                message=body)

        else:
            logger.info(
                f'Unsupported alert type: {bank_rule_config.alert_type}')

            raise GmailRuleProcessingException(
                f"Alert type '{bank_rule_config.alert_type}' is not currently supported")

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

        logger.info(f'Query result count: {len(query_result.messages)}')
        notify_count = 0

        for message_id in query_result.message_ids:
            logger.debug(f'Get email message: {message_id}')

            message = await self._gmail_client.get_message(
                message_id=message_id)

            # If the email is read, ignore it
            if GoogleEmailLabel.Unread not in message.label_ids:
                continue

            logger.info(f'Message eligible for notification: {message_id}')

            body = await self._get_message_body(
                rule=rule,
                message=message)

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

    def _get_message_body(
        self,
        rule: GmailEmailRule,
        message: GmailEmail
    ):
        ArgumentNullException.if_none(rule, 'rule')
        ArgumentNullException.if_none(message, 'message')

        # body = f'From: {message.headers[GoogleEmailHeader.From]}'

        body = f'Rule: {rule.name}'
        body += '\n'
        body += f'Date: {message.timestamp}'
        body += '\n'
        body += '\n'
        body += message.snippet
        body += '\n'
        body += '\n'

        # body += f'{GMAIL_MESSAGE_URL}/{message.message_id}'

        return body
