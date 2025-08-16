from typing import Optional

from clients.gmail_client import GmailClient
from clients.twilio_gateway import TwilioGatewayClient
from domain.google import GmailEmail, GmailEmailRuleModel, GoogleEmailLabel
from framework.logger import get_logger
from models.gmail_models import EmailTagManager, GmailConfig, TagModification
from services.gmail.formatter import MessageFormatter
from services.gmail.processor import BaseRuleProcessor
from framework.clients.feature_client import FeatureClientAsync

logger = get_logger(__name__)


class SmsRuleProcessor(BaseRuleProcessor):
    """Processes SMS notification rules."""

    def __init__(
        self,
        gmail_client: GmailClient,
        message_formatter: MessageFormatter,
        twilio_gateway: TwilioGatewayClient,
        feature_client: FeatureClientAsync,
        config: GmailConfig
    ):
        super().__init__(gmail_client, message_formatter)
        self._twilio_gateway = twilio_gateway
        self._sms_recipient = config.sms_recipient
        self._feature_client = feature_client

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Only process unread messages."""
        return GoogleEmailLabel.Unread in message.label_ids

    async def is_sms_additional_recipient_enabled(self) -> bool:
        """Check if the feature for additional SMS recipients is enabled."""
        return await self._feature_client.is_enabled('gre-sms-additional-recipients')

    async def is_post_action_auto_forward_enabled(self) -> bool:
        """Check if the feature for post-action email auto-forwarding is enabled."""
        return await self._feature_client.is_enabled('gre-sms-post-action-auto-forward')

    async def _process_message(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Send SMS notification for the message."""
        message_body = await self._message_formatter.format_sms_message(rule, message)

        # If post-forward is enabled, prepare recipients and append a note to the SMS body.
        forward_recipients = []
        if getattr(rule.data, 'post_forward_email', False):
            to_field = getattr(rule.data, 'post_forward_email_to', '') or ''
            forward_recipients = [r.strip() for r in to_field.split(',') if r and r.strip()]
            if forward_recipients:
                message_body += f"\n\nOriginal email forwarded to: {', '.join(forward_recipients)}"

        logger.info(f'Sending SMS notification for message: {message_id}')
        await self._twilio_gateway.send_sms(
            recipient=self._sms_recipient,
            message=message_body
        )

        # Send SMS notifications to additional recipients
        # Send SMS notifications to additional recipients
        if rule.data.sms_additional_recipients:
            await self._handle_sms_additional_recipients(
                rule=rule,
                message_body=message_body)

        # Post-rule action email auto-forwarding
        if rule.data.post_forward_email:
            await self._handle_post_action_auto_forward(
                rule=rule,
                message_id=message_id)

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Mark as processed and remove from inbox."""
        return EmailTagManager.get_processed_tags()

    def get_processor_name(self) -> str:
        return "SMS"

    async def _handle_sms_additional_recipients(
        self,
        rule: GmailEmailRuleModel,
        message_body: str
    ):
        enabled = await self._feature_client.is_enabled('gre-sms-additional-recipients')
        if not enabled:
            logger.info('SMS additional recipients feature disabled, skipping additional recipients')
            return

        for recipient in rule.data.sms_additional_recipients:
            logger.info(f'Sending SMS notification to additional recipient: {recipient}')
            await self._twilio_gateway.send_sms(
                recipient=recipient,
                message=message_body)

    async def _handle_post_action_auto_forward(
        self,
        rule: GmailEmail,
        message_id: str
    ):
        enabled = await self.is_post_action_auto_forward_enabled()
        if not enabled:
            logger.info('Post-action auto-forward feature disabled, skipping auto-forward')
            return

        # Split post-forward comma-separated email addresses
        recipients = [x.strip() for x in rule.data.post_forward_email_to.split(',')]
        logger.info(f'Forwarding email {message_id} to: {recipients}')
        for forward_recipient in recipients:
            logger.info(f'Forwarding email {message_id} to: {forward_recipient}')
            await self._gmail_client.forward_email(
                message_id=message_id,
                to_email=forward_recipient,
                cc_emails=rule.data.post_forward_email_cc,
                subject_prefix=f'GRE {rule.name} Auto-Fwd: ',
                outer_content=f'Forwarded via GRE as a post-action for rule {rule.name} ({rule.rule_id}) and original Gmail message {message_id}')
