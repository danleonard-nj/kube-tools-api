import uuid
from datetime import datetime
from typing import List

from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

from data.google.google_email_rule_repository import GoogleEmailRuleRepository
from domain.exceptions import (EmailRuleExistsException,
                               EmailRuleNotFoundException)
from domain.google import GmailEmailRule
from domain.rest import (CreateEmailRuleRequest, DeleteGmailEmailRuleResponse,
                         UpdateEmailRuleRequest)

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

        # Fetch all rules from db
        entities = await self.__email_rule_repository.get_all()

        # Construct domain models from entities
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

            raise EmailRuleExistsException(create_request.name)

        # Create the new rule
        rule = GmailEmailRule(
            rule_id=str(uuid.uuid4()),
            name=create_request.name,
            description=create_request.description,
            query=create_request.query,
            action=create_request.action,
            data=create_request.data,
            max_results=create_request.max_results,
            created_date=datetime.now())

        # Insert the rule entity
        result = await self.__email_rule_repository.insert(
            document=rule.to_dict())

        logger.info(f'Rule / entity: {rule.rule_id} / {result.inserted_id}')

        return rule

    async def delete_rule(
        self,
        rule_id: str
    ) -> DeleteGmailEmailRuleResponse:

        ArgumentNullException.if_none_or_whitespace(rule_id, 'rule_id')

        logger.info(f'Delete rule: {rule_id}')

        # Verify the rule exists by ID provided
        exists = await self.__email_rule_repository.email_rule_exists_by_id(
            rule_id=rule_id)

        logger.info(f'Rule exists: {rule_id}: {exists}')

        # If the rule doesn't exist
        if not exists:
            raise EmailRuleNotFoundException(
                rule_id=rule_id)

        # Delete the rule
        result = await self.__email_rule_repository.delete({
            'rule_id': rule_id
        })

        logger.info(f'Delete result: {result.deleted_count}')

        return DeleteGmailEmailRuleResponse(
            result=result.acknowledged)

    async def get_rule(
        self,
        rule_id: str
    ) -> GmailEmailRule:

        ArgumentNullException.if_none_or_whitespace(rule_id, 'rule_id')

        logger.info(f'Get rule: {rule_id}')

        # Fetch the rule from the db
        entity = await self.__email_rule_repository.get({
            'rule_id': rule_id
        })

        # Handle rule not found
        if entity is None:
            raise EmailRuleNotFoundException(
                rule_id=rule_id)

        # Construct domain model from entity
        rule = GmailEmailRule.from_entity(
            data=entity)

        return rule

    async def update_rule(
        self,
        update_request: UpdateEmailRuleRequest
    ) -> GmailEmailRule:

        ArgumentNullException.if_none(update_request, 'update_request')

        logger.info(f'Update rule: {update_request.rule_id}')

        # Fetch the existing rule (throws on
        # rule not found)
        rule = await self.get_rule(
            rule_id=update_request.rule_id)

        logger.info(f'Updating rule: {rule.to_dict()}')

        # Update fields on the rule from the
        # update request
        rule.update_rule(
            update_request=update_request)

        # Update the rule in the db
        result = await self.__email_rule_repository.replace(
            selector=rule.get_selector(),
            document=rule.to_dict())

        logger.info(f'Updated rule: {result.acknowledged}')

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
