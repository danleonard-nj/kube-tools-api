from typing import Optional
from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from domain.google import GmailEmail, GmailEmailRuleModel, GmailRuleAction, GoogleEmailLabel
from framework.validators import none_or_whitespace
from framework.logger import get_logger

from services.gmail.formatter import MessageFormatter
from models.gmail_models import EmailTagManager, GmailConfig, TagModification
from services.gmail.processor import BaseRuleProcessor
from services.gmail_balance_sync_service import GmailBankSyncService

logger = get_logger(__name__)


class BankSyncRuleProcessor(BaseRuleProcessor):
    """Processes bank sync rules."""

    def __init__(
        self,
        gmail_client: GmailClient,
        message_formatter: MessageFormatter,
        bank_sync_service: GmailBankSyncService,
        twilio_gateway: TwilioGatewayClient,
        config: GmailConfig
    ):
        super().__init__(gmail_client, message_formatter)
        self._bank_sync_service = bank_sync_service
        self._twilio_gateway = twilio_gateway
        self._sms_recipient = config.sms_recipient

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Only process unread messages."""
        return GoogleEmailLabel.Unread in message.label_ids

    async def _process_message(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Process bank sync for the message."""
        # Get bank sync configuration
        bank_key = rule.data.bank_sync_bank_key
        alert_type = rule.data.bank_sync_alert_type

        if none_or_whitespace(bank_key):
            raise Exception(
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
        rule: GmailEmailRuleModel,
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
            raise Exception(
                f"Balance sync alert type '{alert_type}' is not currently supported"
            )

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Mark as processed and remove from inbox."""
        return EmailTagManager.get_processed_tags()

    def get_processor_name(self) -> str:
        return "bank sync"
