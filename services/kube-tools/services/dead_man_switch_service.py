from datetime import datetime
from tracemalloc import get_object_traceback
from typing import List
from framework.clients.feature_client import FeatureClientAsync
from framework.logger import get_logger
from framework.exceptions.nulls import ArgumentNullException
from gevent import config

from data.dead_man_configuration_repository import \
    DeadManConfigurationRepository

from data.dead_man_switch_repository import DeadManSwitchRepository
from domain.exceptions import SwitchConfigurationNotFoundException, SwitchExistsException, SwitchNotFoundException
from domain.features import Feature
from domain.health import DeadManSwitch, DeadManSwitchConfiguration
from domain.rest import CreateDeadManConfigurationRequest, CreateSwitchRequest, DisarmSwitchRequest, UpdateDeadManConfigurationRequest

logger = get_logger(__name__)


class DeadManSwitchService:
    def __init__(
        self,
        feature_client: FeatureClientAsync,
        switch_repository: DeadManSwitchRepository,
        config_repository: DeadManConfigurationRepository
    ):
        ArgumentNullException.if_none(switch_repository, 'switch_repository')
        ArgumentNullException.if_none(config_repository, 'config_repository')
        ArgumentNullException.if_none(feature_client, 'feature_client')

        self.__switch_repository = switch_repository
        self.__config_repository = config_repository
        self.__feature_client = feature_client

    async def disarm_switch(
        self,
        request: DisarmSwitchRequest
    ) -> DeadManSwitch:

        ArgumentNullException.if_none_or_whitespace(
            request.switch_id, 'switch_id')

        # TODO: Verify we're within the configured limits (i.e. is a disarm required)

        entity = await self.__switch_repository.get({
            'switch_id': request.switch_id
        })

        if entity is None:
            logger.info(f'Switch does not exist: {request.switch_id}')
            raise SwitchNotFoundException(
                switch_id=request.switch_id)

        switch = DeadManSwitch.from_entity(
            data=entity)

        # Disarm the switch by flipping last disarm date
        # to now
        switch.last_disarm = datetime.utcnow()
        switch.modified_date = datetime.utcnow()

        logger.info(
            f'Disarming switch {switch.switch_id}: {switch.last_disarm}')

        updated = switch.to_dict()
        logger.info(f'Updated switch: {switch.to_dict()}')

        result = await self.__switch_repository.replace(
            selector=switch.get_selector(),
            document=updated)

        logger.info(f'Switch update result: {result.modified_count}')

        return updated

    async def __validate_switch(
        self,
        switch_name: str,
        configuration_id: str
    ) -> None:
        # Verify the name is not already taken
        name_exists = await self.__switch_repository.switch_exists_by_name(
            switch_name=switch_name)

        if name_exists:
            logger.info(f'Switch name conflict: {switch_name}')
            raise SwitchExistsException(
                switch_name=switch_name)

        # Verify the provided configuration exists
        config_exists = await self.__config_repository.configuration_exists(
            configuration_id=configuration_id)

        if not config_exists:
            logger.info(
                f'Invalid configuration provided for switch: {configuration_id}')
            raise SwitchConfigurationNotFoundException(
                configuration_id=configuration_id)

    async def create_switch(
        self,
        request: CreateSwitchRequest
    ) -> DeadManSwitch:

        ArgumentNullException.if_none(request, 'request')
        ArgumentNullException.if_none_or_whitespace(
            request.configuration_id, 'configuration_id')
        ArgumentNullException.if_none_or_whitespace(
            request.switch_name, 'switch_name')

        logger.info(
            f'Create switch from configuration: {request.configuration_id}')

        # TODO: Validate config ID

        # Verify switch is valid
        await self.__validate_switch(
            switch_name=request.switch_name,
            configuration_id=request.configuration_id)

        switch = DeadManSwitch.create_dead_mans_switch(
            configuration_id=request.configuration_id,
            switch_name=request.switch_name)

        logger.info(f'New switch created: {switch.switch_id}')

        result = await self.__switch_repository.insert(
            document=switch.to_dict())

        logger.info(f'Create swith insert: {result.inserted_id}')

        return switch

    async def __is_feature_enabled(
        self
    ) -> bool:

        if not await self.__feature_client.is_enabled(
                feature_key=Feature.DeadManSwitch):

            logger.info(f'Feature is disabled: {Feature.DeadManSwitch}')
            return False
        return True

    async def create_configuration(
        self,
        request: CreateDeadManConfigurationRequest
    ) -> DeadManSwitchConfiguration:

        ArgumentNullException.if_none(request, 'request')

        logger.info(f'Create dead man switch config: {request.to_dict()}')

        # Generate the new configuration
        configuration = DeadManSwitchConfiguration.create_configuration(
            configuration_name=request.configuration_name,
            interval_hours=request.interval_hours,
            grace_period_hours=request.grace_period_hours,
            alert_type=request.alert_type,
            alert_address=request.alert_address)

        logger.info(f'Created configuration: {configuration.configuration_id}')

        # Insert the new configuration
        result = await self.__config_repository.insert(
            document=configuration.to_dict())
        logger.info(f'Inserted configuration entity: {result.inserted_id}')

        return configuration

    async def update_configuration(
        self,
        request: UpdateDeadManConfigurationRequest
    ):
        ArgumentNullException.if_none(request, 'request')

        configuration = await self.get_configurations(
            configuration_id=request.configuration_id)

        configuration.update_configuration(
            interval_hours=request.interval_hours,
            grace_period_hours=request.grace_period_hours,
            alert_type=request.alert_type,
            alert_address=request.alert_address)

        result = await self.__config_repository.replace(
            selector=configuration.get_selector(),
            document=configuration.to_dict())

        logger.info(f'Configuration entities updated: {result.modified_count}')

        return configuration

    async def get_configuration(
        self,
        configuration_id: str
    ) -> DeadManSwitchConfiguration:

        ArgumentNullException.if_none_or_whitespace(
            configuration_id, 'configuration_id')

        entity = await self.__config_repository.get({
            'configuration_id': configuration_id
        })

        if entity is None:
            logger.info(f'No configuration found: {configuration_id}')
            raise SwitchConfigurationNotFoundException(
                configuration_id=configuration_id)

        configuration = DeadManSwitchConfiguration.from_entity(
            data=entity)

        return configuration

    async def get_configurations(
        self
    ) -> List[DeadManSwitchConfiguration]:

        entities = await self.__config_repository.get_all()
        logger.info(f'Switch configurations fetched: {len(entities)}')

        configurations = [DeadManSwitchConfiguration.from_entity(data=entity)
                          for entity in entities]

        return configurations
