import asyncio
from typing import Dict, List

from framework.configuration import Configuration
from framework.logger import get_logger

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from constants.google import GmailRuleAction, GoogleEmailHeader, GoogleEmailLabel
from domain.google import GmailEmail, GmailEmailHeaders, GmailEmailRule
from services.bank_service import BankService
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)

WELLS_FARGO_RULE_ID = '7062d7af-c920-4f2e-bdc5-e52314d69194'
WELLS_FARGO_BALANCE_EMAIL_KEY = 'Balance summary'
WELLS_FARGO_BANK_KEY = 'wells-fargo'


class GmailService:
    def __init__(
        self,
        configuration: Configuration,
        gmail_client: GmailClient,
        rule_service: GmailRuleService,
        bank_service: BankService,
        twilio_gateway: TwilioGatewayClient
    ):
        self.__gmail_client = gmail_client
        self.__rule_service = rule_service
        self.__twilio_gateway = twilio_gateway
        self.__bank_service = bank_service

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

        asyncio.create_task(self.__rule_service.log_results(
            results=run_results))

        return run_results

    async def process_archive_rule(
        self,
        rule: GmailEmailRule
    ) -> List[str]:

        # Query the inbox w/ the defined rule query
        query_result = await self.__gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Result count: {len(query_result.messages or [])}')

        archived = 0
        for message_id in query_result.message_ids or []:
            message = await self.__gmail_client.get_message(
                message_id=message_id)

            if GoogleEmailLabel.Inbox not in message.label_ids:
                continue

            logger.info(f'Rule: {rule.name}: Archiving email: {message_id}')

            archived += 1
            await self.__gmail_client.archive_message(
                message_id=message_id)

        return archived

    async def process_sms_rule(
        self,
        rule: GmailEmailRule
    ):
        logger.info(f'Processing SMS rule: {rule.name}')

        # Query the inbox w/ the defined rule query
        query_result = await self.__gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        logger.info(f'Query result count: {len(query_result.messages)}')
        notify_count = 0

        for message_id in query_result.message_ids:
            logger.debug(f'Get email message: {message_id}')

            message = await self.__gmail_client.get_message(
                message_id=message_id)

            # If the email is read, ignore it
            if GoogleEmailLabel.Unread not in message.label_ids:
                continue

            logger.info(f'Message eligible for notification: {message_id}')

            body = await self.__get_message_body(
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

            logger.info(f'Tags add/remove: {to_add}: {to_remove}')

            notify_count += 1

        return notify_count

    async def __get_message_body(
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

        if rule.rule_id == WELLS_FARGO_RULE_ID:
            logger.info('Wells Fargo rule detected')

            if WELLS_FARGO_BALANCE_EMAIL_KEY in message.snippet:
                logger.info('Wells Fargo balance email detected')
                await self.handle_bank_email(
                    message=message)

        return body

    async def handle_bank_email(
        self,
        message: GmailEmail
    ):

        try:
            balance = message.snippet.split('Ending Balance: ')[
                1].split(' ')[0].replace('$', '')

            await self.__bank_service.capture_balance(
                bank_key=WELLS_FARGO_BANK_KEY,
                balance=float(balance))

        except Exception as ex:
            logger.exception(f'Error parsing balance: {ex.message}')
            balance = 0.0
