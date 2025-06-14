import asyncio
from typing import Dict

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from domain.enums import ProcessGmailRuleResultType
from domain.google import (GmailEmailRuleModel, GmailRuleAction, GoogleClientScope,
                           ProcessGmailRuleResponse)
from framework.concurrency import TaskCollection
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from models.gmail_models import GmailConfig
from services.gmail.archive_processor import ArchiveRuleProcessor
from services.gmail.bank_processor import BankSyncRuleProcessor
from services.gmail.sms_processor import SmsRuleProcessor
from services.gmail_balance_sync_service import GmailBankSyncService
from services.gmail_rule_service import GmailRuleService

logger = get_logger(__name__)


class GmailServiceError(Exception):
    pass


class GmailService:
    def __init__(
        self,
        config: GmailConfig,
        gmail_client: GmailClient,
        rule_service: GmailRuleService,
        bank_sync_service: GmailBankSyncService,
        twilio_gateway: TwilioGatewayClient,
        archive_processor: ArchiveRuleProcessor,
        sms_processor: SmsRuleProcessor,
        bank_sync_processor: BankSyncRuleProcessor
    ):
        self._gmail_client = gmail_client
        self._rule_service = rule_service
        self._twilio_gateway = twilio_gateway
        self._bank_sync_service = bank_sync_service
        self._sms_recipient = config.sms_recipient

        self._semaphore = asyncio.Semaphore(config.concurrency)

        # Cache rule processors
        self._rule_processors = {
            GmailRuleAction.Archive: archive_processor,
            GmailRuleAction.SMS: sms_processor,
            GmailRuleAction.BankSync: bank_sync_processor
        }

    async def run_mail_service(self) -> Dict[str, int]:
        logger.info(f'Gathering rules for Gmail rule service')
        rules = await self._rule_service.get_rules()
        if not any(rules):
            logger.info(f'No rules found to process')
            return []
        rules.reverse()
        logger.info(f'Rules gathered: {len(rules)}')
        await self._gmail_client.ensure_auth(scopes=[GoogleClientScope.Gmail])
        process_rules = TaskCollection(*[
            self.process_rule(rule=rule)
            for rule in rules
        ])
        results = await process_rules.run()
        results.sort(key=lambda x: x.rule_name)
        return results

    async def process_rule(self, rule: GmailEmailRuleModel) -> ProcessGmailRuleResponse:
        ArgumentNullException.if_none(rule, 'process_request')
        async with self._semaphore:
            try:
                logger.info(f'Processing rule: {rule.rule_id}: {rule.name}')
                processor = self._rule_processors.get(rule.action)
                if not processor:
                    raise GmailServiceError(f'Unsupported rule action: {rule.action}')
                affected_count = await processor.process_rule(rule)
                logger.info(f'Rule: {rule.name}: Emails affected: {affected_count}')
                return ProcessGmailRuleResponse(
                    status=ProcessGmailRuleResultType.Success,
                    rule=rule,
                    affected_count=affected_count)
            except Exception as ex:
                logger.exception(f'Failed to process rule: {rule.rule_id}: {rule.name}: {str(ex)}')
                return ProcessGmailRuleResponse(
                    status=ProcessGmailRuleResultType.Failure,
                    rule=rule)
