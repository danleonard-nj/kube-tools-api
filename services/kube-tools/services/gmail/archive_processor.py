from typing import Optional

from domain.google import GmailEmail, GmailEmailRule, GoogleEmailLabel
from framework.logger import get_logger
from models.gmail_models import TagModification
from services.gmail.processor import BaseRuleProcessor

logger = get_logger(__name__)


class ArchiveRuleProcessor(BaseRuleProcessor):
    """Processes archive rules."""

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Only process messages that are still in inbox."""
        return GoogleEmailLabel.Inbox in message.label_ids

    async def _process_message(
        self,
        rule: GmailEmailRule,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Archive the message."""
        await self._gmail_client.archive_message(message_id=message_id)
        logger.info(f'Archived email: {message_id}')

    def _get_tag_modification(self) -> Optional[TagModification]:
        """Archive rules don't need additional tag modifications."""
        return None

    def get_processor_name(self) -> str:
        return "archive"
