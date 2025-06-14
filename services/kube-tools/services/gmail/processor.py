

from abc import ABC, abstractmethod
from typing import Optional

from clients.gmail_client import GmailClient
from domain.google import GmailEmail, GmailEmailRuleModel
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from services.gmail.formatter import MessageFormatter
from models.gmail_models import TagModification

logger = get_logger(__name__)


class BaseRuleProcessor(ABC):
    """Base class for rule processors with common functionality."""

    def __init__(
        self,
        gmail_client: GmailClient,
        message_formatter: MessageFormatter
    ):
        self._gmail_client = gmail_client
        self._message_formatter = message_formatter

    async def process_rule(self, rule: GmailEmailRuleModel) -> int:
        """Process a rule and return the number of affected emails."""
        ArgumentNullException.if_none(rule, 'rule')

        logger.info(f'Processing {self.get_processor_name()} rule: {rule.name}')

        # Query inbox with rule query
        query_result = await self._gmail_client.search_inbox(
            query=rule.query,
            max_results=rule.max_results
        )

        if query_result is None or not query_result.message_ids:
            logger.info(f'No emails found for rule: {rule.name}')
            return 0

        logger.info(f'Query result count: {query_result.count}')
        processed_count = 0

        for message_id in query_result.message_ids:
            try:
                message = await self._gmail_client.get_message(message_id=message_id)

                if not self._should_process_message(message):
                    continue

                logger.info(f'Processing message {message_id} for rule: {rule.name}')

                # Process the specific message
                await self._process_message(rule, message, message_id)

                # Apply tag modifications
                tag_modification = self._get_tag_modification()
                if tag_modification:
                    await self._apply_tag_modification(message_id, tag_modification)

                processed_count += 1

            except Exception as ex:
                logger.exception(f'Failed to process message {message_id}: {str(ex)}')
                # Continue processing other messages

        return processed_count

    def _should_process_message(self, message: GmailEmail) -> bool:
        """Determine if a message should be processed."""
        # Default implementation - can be overridden by subclasses
        return True

    async def _apply_tag_modification(
        self,
        message_id: str,
        tag_modification: TagModification
    ) -> None:
        """Apply tag modifications to a message."""
        if tag_modification.to_add or tag_modification.to_remove:
            await self._gmail_client.modify_tags(
                message_id=message_id,
                to_add=tag_modification.to_add,
                to_remove=tag_modification.to_remove
            )
            logger.info(f'Tags applied - Add: {tag_modification.to_add}, Remove: {tag_modification.to_remove}')

    @abstractmethod
    async def _process_message(
        self,
        rule: GmailEmailRuleModel,
        message: GmailEmail,
        message_id: str
    ) -> None:
        """Process a specific message according to rule logic."""
        pass

    @abstractmethod
    def _get_tag_modification(self) -> Optional[TagModification]:
        """Get the tag modification for this processor type."""
        pass

    @abstractmethod
    def get_processor_name(self) -> str:
        """Get the name of this processor for logging."""
        pass
