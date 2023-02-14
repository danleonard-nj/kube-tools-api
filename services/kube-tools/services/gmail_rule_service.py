from typing import List

from framework.logger import get_logger

from data.google.google_email_rule_repository import GoogleEmailRuleRepository
from domain.google import GmailEmailRule

logger = get_logger(__name__)


class GmailRuleService:
    def __init__(
        self,
        email_rule_repository: GoogleEmailRuleRepository,
    ):
        self.__email_rule_repository = email_rule_repository

    async def get_rules(
        self
    ) -> List[GmailEmailRule]:
        entities = await self.__email_rule_repository.get_all()

        rules = [
            GmailEmailRule.from_entity(data=entity)
            for entity in entities
        ]

        return rules
