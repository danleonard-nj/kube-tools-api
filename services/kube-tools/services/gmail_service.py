from typing import List

from framework.logger import get_logger

from clients.gmail_client import GmailClient
from domain.google import GmailEmailRule, GmailRuleAction
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)


class GmailService:
    def __init__(
        self,
        gmail_client: GmailClient,
        rule_service: GmailRuleService
    ):
        self.__gmail_client = gmail_client
        self.__rule_service = rule_service

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
        query_result = await self.__gmail_client.search_inbox(
            query=rule.query)

        logger.info(f'Result count: {len(query_result.messages)}')

        for message_id in query_result.message_ids:
            logger.info(f'Rule: {rule.name}: Archiving email: {message_id}')

            await self.__gmail_client.archive_message(
                message_id=message_id)

        return len(query_result.message_ids)
