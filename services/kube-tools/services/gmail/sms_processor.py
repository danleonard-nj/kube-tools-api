from typing import Optional

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from domain.google import GmailEmail, GmailEmailRuleModel, GoogleEmailLabel
from framework.logger import get_logger
from models.gmail_models import EmailTagManager, GmailConfig, TagModification
from services.gmail.formatter import MessageFormatter
from services.gmail.processor import BaseRuleProcessor

logger = get_logger(__name__)


class SmsRuleProcessor(BaseRuleProcessor):
    """Processes SMS notification rules."""

    def __init__(
        self,
        gmail_client: GmailClient,
        message_formatter: MessageFormatter,
        twilio_gateway: TwilioGatewayClient,
        config: GmailConfig
    ):
        super().__init__(gmail_client, message_formatter)
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
        """Send SMS notification for the message."""
        message_body = await self._message_formatter.format_sms_message(rule, message)

        logger.info(f'Sending SMS notification for message: {message_id}')
        await self._twilio_gateway.send_sms(
            recipient=self._sms_recipient,
            message=message_body
        )

        # Send SMS notifications to additional recipients
        if rule.data.sms_additional_recipients:
            for recipient in rule.data.sms_additional_recipients:
                logger.info(f'Sending SMS notification to additional recipient: {recipient}')
                await self._twilio_gateway.send_sms(
                    recipient=recipient,
                    message=message_body)

        # Post-rule action email auto-forwarding
        if rule.data.post_forward_email:
            recipients = [r.strip() for r in rule.data.post_forward_email_to.split(',') if r and r.strip()]
            logger.info(f'Forwarding email {message_id} to: {recipients}')
            for forward_recipient in recipients:
                logger.info(f'Forwarding email {message_id} to: {forward_recipient}')
                await self._gmail_client.forward_email(
                    message_id=message_id,
                    to_email=forward_recipient,
                    cc_emails=rule.data.post_forward_email_cc,
                    subject_prefix='GRE Auto-Fwd: ',
                    outer_content=f'Forwarded via GRE as a post-action for rule {rule.name} ({rule.id}) and original Gmail message {message_id}'
                )

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Mark as processed and remove from inbox."""
        return EmailTagManager.get_processed_tags()

    def get_processor_name(self) -> str:
        return "SMS"
