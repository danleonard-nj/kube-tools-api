from typing import Optional

from domain.google import GmailEmail, GmailEmailRuleModel, GoogleEmailLabel
from framework.logger import get_logger
from models.gmail_models import EmailTagManager, TagModification
from services.gmail.processor import BaseRuleProcessor

logger = get_logger(__name__)


class ForwardRuleProcessor(BaseRuleProcessor):
    """Processes email forwarding rules."""

    def __init__(self, gmail_client, message_formatter):
        super().__init__(gmail_client, message_formatter)
        self._current_rule: Optional[GmailEmailRuleModel] = None

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Only process unread messages that are not starred."""
        return (GoogleEmailLabel.Unread in message.label_ids and
                GoogleEmailLabel.Starred not in message.label_ids)

    async def _process_message(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Forward the email to the specified recipients."""
        self._current_rule = rule

        if not rule.data.forward_to_email:
            logger.warning(f'No forward_to_email specified for rule: {rule.name}')
            return

        # Split comma-separated email addresses
        recipients = [x.strip() for x in rule.data.forward_to_email.split(',')]

        for recipient in recipients:
            logger.info(f'Forwarding email {message_id} to: {recipient}')
            await self._gmail_client.forward_email(
                message_id=message_id,
                to_email=recipient,
                cc_emails=rule.data.forward_cc_email.split(',') if rule.data.forward_cc_email else None,
                subject_prefix=f'GRE Fwd: ',
                outer_content=f'Forwarded via Gmail Rule Engine (rule: {rule.name}, rule_id: {rule.rule_id})'
            )

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Mark as processed and remove from inbox, unless forward_keep_unread is True."""
        if self._current_rule and self._current_rule.data.forward_keep_unread:
            logger.info('forward_keep_unread is True, marking as read but keeping unread/inbox status')
            return EmailTagManager.get_unread_forward_tags()

        return EmailTagManager.get_processed_tags()

    def get_processor_name(self) -> str:
        return "forward"
