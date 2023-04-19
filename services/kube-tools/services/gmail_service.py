from typing import Dict, List

from framework.configuration import Configuration
from framework.logger import get_logger

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from constants.google import GmailRuleAction, GoogleEmailHeader, GoogleEmailLabel
from domain.google import GmailEmail, GmailEmailRule
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)


class GmailService:
    def __init__(
        self,
        configuration: Configuration,
        gmail_client: GmailClient,
        rule_service: GmailRuleService,
        twilio_gateway: TwilioGatewayClient
    ):
        self.__gmail_client = gmail_client
        self.__rule_service = rule_service
        self.__twilio_gateway = twilio_gateway

        self.__sms_recipient = configuration.gmail.get(
            'sms_recipient')

    async def run_mail_service(
        self
    ) -> Dict[str, int]:

        logger.info(f'Gathering rules for Gmail rule service')

        run_results = dict()

        rules = await self.__rule_service.get_rules()
        logger.info(f'Rules gathered: {len(rules)}')

        for rule in rules:
            logger.info(f'Processing rule: {rule.rule_id}: {rule.name}')

            # Default affected count
            affected_count = 0

            # Process an archival rule
            if rule.action == GmailRuleAction.Archive:
                logger.info(f'Rule type: {GmailRuleAction.Archive}')

                affected_count = await self.process_archive_rule(
                    rule=rule)

            # Process an SMS rule
            if rule.action == GmailRuleAction.SMS:
                logger.info(f'Rule type: {GmailRuleAction.SMS}')

                affected_count = await self.process_sms_rule(
                    rule=rule)

            run_results[rule.name] = affected_count
            logger.info(
                f'Rule: {rule.name}: Emails affected: {affected_count}')

        return run_results

    async def process_archive_rule(
        self,
        rule: GmailEmailRule
    ) -> List[str]:

        # Query the inbox w/ the defined rule query
        query_result = await self.__gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Result count: {len(query_result.messages)}')

        for message_id in query_result.message_ids:
            message = await self.__gmail_client.get_message(
                message_id=message_id)

            if GoogleEmailLabel.Inbox not in message.label_ids:
                continue

            logger.info(f'Rule: {rule.name}: Archiving email: {message_id}')

            await self.__gmail_client.archive_message(
                message_id=message_id)

        return len(query_result.message_ids)

    async def process_sms_rule(
        self,
        rule: GmailEmailRule
    ):
        # Query the inbox w/ the defined rule query
        query_result = await self.__gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Result count: {len(query_result.messages)}')
        notify_count = 0

        for message_id in query_result.message_ids:
            logger.info(f'Get email message: {message_id}')

            message = await self.__gmail_client.get_message(
                message_id=message_id)

            # If the email is read, ignore it
            if GoogleEmailLabel.Unread not in message.label_ids:
                continue

            logger.info('Message unread, sending notification')

            body = self.__get_message_body(
                rule=rule,
                message=message)

            logger.info(f'Message body: {body}')

            # Send the email snippet in the message body
            await self.__twilio_gateway.send_sms(
                recipient=self.__sms_recipient,
                message=body)

            # Mark read the email so another notification isn't sent
            to_add = [GoogleEmailLabel.Starred]

            to_remove = [GoogleEmailLabel.Unread,
                         GoogleEmailLabel.Inbox]

            await self.__gmail_client.modify_tags(
                message_id=message_id,
                to_add=to_add,
                to_remove=to_remove)

            await self.__rule_service.update_rule_items_caught_count(
                rule_id=rule.rule_id,
                count_processed=rule.count_processed)

            notify_count += 1

        return notify_count

    def __get_message_body(
        self,
        rule: GmailEmailRule,
        message: GmailEmail
    ):
        body = f'From: {message.headers[GoogleEmailHeader.From]}'
        body = f'Rule: {rule.name} ({rule.rule_id})'
        body += '\n'
        body += f'Date: {message.timestamp}'
        body += '\n'
        body += '\n'
        body += message.snippet
        body += '\n'
        body += '\n'
        body += f'https://mail.google.com/mail/u/0/#inbox/{message.message_id}'

        return body
