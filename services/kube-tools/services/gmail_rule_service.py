import uuid
from datetime import datetime
from typing import List

from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

from data.google.google_email_rule_repository import GoogleEmailRuleRepository
from domain.google import GmailEmailRule
from domain.rest import CreateEmailRuleRequest

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

        logger.info(f'Fetching all email rules')

        entities = await self.__email_rule_repository.get_all()

        rules = [
            GmailEmailRule.from_entity(data=entity)
            for entity in entities
        ]

        logger.info(f'{len(rules)} rules retrieved')

        return rules

    async def create_rule(
        self,
        create_request: CreateEmailRuleRequest
    ) -> GmailEmailRule:

        ArgumentNullException.if_none(create_request, 'create_request')

        logger.info(f'Create email rule: {create_request.to_dict()}')

        # Query existing rules w/ requested name
        existing = await self.__email_rule_repository.get({
            'name': create_request.name
        })

        logger.info(f'Existing entity: {existing}')

        # Handle rule name conflicts
        if existing is not None:
            logger.error(f'Rule {create_request.name} exists: {existing}')

            raise Exception(f"A rule with the name '{create_request.name}'")

        # Create the new rule
        rule = GmailEmailRule(
            rule_id=str(uuid.uuid4()),
            name=create_request.name,
            description=create_request.description,
            query=create_request.query,
            action=create_request.action,
            data=create_request.data,
            created_date=datetime.now(),
            create_request=0)

        # Insert the rule entity
        result = await self.__email_rule_repository.insert(
            document=rule.to_dict())

        logger.info(f'Rule / entity: {rule.rule_id} / {result.inserted_id}')

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
