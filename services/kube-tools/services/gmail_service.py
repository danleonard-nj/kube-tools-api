from typing import Dict, List

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from constants.google import (GmailRuleAction, GoogleEmailHeader,
                              GoogleEmailLabel)
from domain.bank import BankRuleConfiguration
from domain.enums import ProcessGmailRuleResultType
from domain.google import GmailEmail, GmailEmailRule
from domain.rest import ProcessGmailRuleRequest, ProcessGmailRuleResponse
from framework.concurrency import TaskCollection
from framework.configuration import Configuration
from framework.logger import get_logger
from services.gmail_balance_sync_service import GmailBankSyncService
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)


GMAIL_MESSAGE_URL = 'https://mail.google.com/mail/u/0/#inbox'


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

        run_results = []

        rules = await self._rule_service.get_rules()
        rules.reverse()

        logger.info(f'Rules gathered: {len(rules)}')

        tasks = TaskCollection()

        for rule in rules:
            process_request = ProcessGmailRuleRequest({
                'rule': rule.to_dict()
            })

            async def capture_response(req: ProcessGmailRuleRequest):
                response = await self.process_rule(
                    process_request=req)

                run_results.append({
                    'rule': rule,
                    'results': response
                })

            tasks.add_task(capture_response(req=process_request))

        await tasks.run()

        return run_results

    async def process_rule(
        self,
        process_request: ProcessGmailRuleRequest
    ):
        try:
            logger.info(
                f'Parsing rule to process: {process_request.to_dict()}')

            if process_request.rule is None:
                raise Exception('No rule provided to process')

            rule = GmailEmailRule.from_request_body(
                data=process_request.rule)

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

            if rule.action == GmailRuleAction.BankSync:
                logger.info(f'Rule type: {GmailRuleAction.BankSync}')

                affected_count = await self.process_bank_sync_rule(
                    rule=rule)

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

        # Query the inbox w/ the defined rule query
        query_result = await self._gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results)

        archived = 0

        if query_result is None:
            logger.info(f'No emails found for rule: {rule.name}')
            return archived

        logger.info(f'Result count: {len(query_result.messages or [])}')
        for message_id in query_result.message_ids or []:
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

        body = await self.__get_message_body(
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

            raise Exception(
                f"Alert type '{bank_rule_config.alert_type}' is not currently supported")

    async def process_sms_rule(
        self,
        rule: GmailEmailRule
    ):
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

            body = await self.__get_message_body(
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
        body += f'{GMAIL_MESSAGE_URL}/{message.message_id}'

        return body
