import uuid
from datetime import datetime
from typing import List

from framework.logger import get_logger

from data.google.google_email_rule_repository import GoogleEmailRuleRepository
from domain.google import GmailEmailRule
from domain.rest import CreateEmailRuleRequest
from framework.exceptions.nulls import ArgumentNullException

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

    async def create_rule(
        self,
        create_request: CreateEmailRuleRequest
    ):
        ArgumentNullException.if_none(create_request, 'create_request')

        existing = await self.__email_rule_repository.get({
            'name': create_request.name
        })

        if existing is not None:
            raise Exception(f"A rule with the name '{create_request.name}'")

        rule = GmailEmailRule(
            rule_id=str(uuid.uuid4()),
            name=create_request.name,
            description=create_request.description,
            query=create_request.query,
            action=create_request.action,
            data=create_request.data,
            created_date=datetime.now(),
            create_request=0)

        await self.__email_rule_repository.insert(
            document=rule.to_dict())

        return rule

    async def update_rule_items_caught_count(
        self,
        rule_id: str,
        count_processed: int
    ):
        ArgumentNullException.if_none_or_whitespace(rule_id, 'rule_id')

        logger.info(
            f'Rule: {rule_id}: Uptating count processed: {count_processed}')

        # Will throw on non-numeric value
        mod = {
            '$inc': {
                'count_processed': count_processed or 0
            }
        }

        await self.__email_rule_repository.collection.update_one(
            {'rule_id': rule_id},
            mod)

    async def get_all_rules(
        self
    ):
        logger.info('Get email rule list')

        await self.__email_rule_repository.get_all()
