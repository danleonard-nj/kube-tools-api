import uuid
from datetime import datetime
from typing import Dict, List

from data.google.google_email_log_repository import GoogleEmailLogRepository
from data.google.google_email_rule_repository import GoogleEmailRuleRepository
from domain.features import Feature
from domain.google import (CreateEmailRuleRequestModel,
                           DeleteGmailEmailRuleResponseModel, EmailRuleLog,
                           GmailEmailRuleModel, UpdateEmailRuleRequestModel)
from framework.clients.feature_client import FeatureClientAsync
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


class GmailRuleService:
    def __init__(
        self,
        email_rule_repository: GoogleEmailRuleRepository,
        log_repository: GoogleEmailLogRepository,
        feature_client: FeatureClientAsync
    ):
        self._email_rule_repository = email_rule_repository
        self._log_repository = log_repository
        self._feature_client = feature_client

    async def get_rules_by_name(
        self,
        rule_names: List[str]
    ):
        logger.info(f'Fetching rules by name: {rule_names}')

        entities = await self._email_rule_repository.get_email_rules_by_names(
            names=rule_names)

        logger.info(f'Rules retrieved: {len(entities)}')

        return [GmailEmailRuleModel.from_entity(data=entity) for entity in entities]

    async def get_rules(
        self
    ) -> List[GmailEmailRuleModel]:

        logger.info(f'Fetching all email rules')

        # Fetch all rules from db
        entities = await self._email_rule_repository.get_all()

        # Construct domain models from entities
        rules = [
            GmailEmailRuleModel.from_entity(data=entity)
            for entity in entities
        ]

        logger.info(f'{len(rules)} rules retrieved')

        active = [rule for rule in rules if rule.is_active]

        logger.info(f'{len(active)} active rules retrieved')

        return active

    async def create_rule(
        self,
        create_request: CreateEmailRuleRequestModel
    ) -> GmailEmailRuleModel:

        ArgumentNullException.if_none(create_request, 'create_request')

        logger.info(f'Create email rule: {create_request.to_dict()}')

        # Query existing rules w/ requested name
        existing = await self._email_rule_repository.get({
            'name': create_request.name
        })

        logger.info(f'Existing entity: {existing}')

        # Handle rule name conflicts
        if existing is not None:
            logger.error(f'Rule {create_request.name} exists: {existing}')

            raise Exception(f"A rule with the name '{create_request.name}' already exists")

        # Create the new rule
        rule = GmailEmailRuleModel(
            rule_id=str(uuid.uuid4()),
            name=create_request.name,
            description=create_request.description,
            query=create_request.query,
            action=create_request.action,
            data=create_request.data,
            max_results=create_request.max_results,
            is_active=True,
            created_date=datetime.now())

        # Insert the rule entity
        result = await self._email_rule_repository.insert(
            document=rule.to_dict())

        logger.info(f'Rule / entity: {rule.rule_id} / {result.inserted_id}')

        return rule

    async def delete_rule(
        self,
        rule_id: str
    ) -> DeleteGmailEmailRuleResponseModel:

        ArgumentNullException.if_none_or_whitespace(rule_id, 'rule_id')

        logger.info(f'Delete rule: {rule_id}')

        # Verify the rule exists by ID provided
        exists = await self._email_rule_repository.email_rule_exists_by_id(
            rule_id=rule_id)

        logger.info(f'Rule exists: {rule_id}: {exists}')

        # If the rule doesn't exist
        if not exists:
            raise Exception(f"No rule with the ID '{rule_id}' exists")

        # Delete the rule
        result = await self._email_rule_repository.delete({
            'rule_id': rule_id
        })

        logger.info(f'Delete result: {result.deleted_count}')

        return DeleteGmailEmailRuleResponseModel(result=result.acknowledged)

    async def get_rule(
        self,
        rule_id: str
    ) -> GmailEmailRuleModel:

        ArgumentNullException.if_none_or_whitespace(rule_id, 'rule_id')

        logger.info(f'Get rule: {rule_id}')

        # Fetch the rule from the db
        entity = await self._email_rule_repository.get({
            'rule_id': rule_id
        })

        # Handle rule not found
        if entity is None:
            raise Exception(f"No rule with the ID '{rule_id}' exists")

        # Construct domain model from entity
        rule = GmailEmailRuleModel.from_entity(
            data=entity)

        return rule

    async def update_rule(
        self,
        update_request: UpdateEmailRuleRequestModel
    ) -> GmailEmailRuleModel:

        ArgumentNullException.if_none(update_request, 'update_request')

        logger.info(f'Update rule: {update_request.rule_id}')

        # Fetch the existing rule (throws on
        # rule not found)
        rule = await self.get_rule(rule_id=update_request.rule_id)

        # Update fields on the rule from the
        # update request
        rule.update_rule(update_request=update_request)

        # Update the rule in the db
        result = await self._email_rule_repository.replace(
            selector=rule.get_selector(),
            document=rule.to_dict())

        logger.info(f'Updated rule: {result.modified_count}')

        return rule

    async def log_results(
        self,
        results: Dict
    ):
        logger.info(f'Logging rule service results: {results}')

        is_enabled = await self._feature_client.is_enabled(
            feature_key=Feature.EmailRuleLogIngestion)

        if not is_enabled:
            logger.info(f'Email rule log ingestion is disabled')
            return

        record = EmailRuleLog(
            log_id=str(uuid.uuid4()),
            results=results,
            created_date=DateTimeUtil.timestamp())

        logger.info(f'Log record: {record.to_dict()}')

        await self._log_repository.insert(
            document=record.to_dict())
