from datetime import datetime
from typing import Dict, List

from framework.clients.feature_client import FeatureClientAsync
from framework.concurrency import TaskCollection
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger

from data.dead_man_configuration_repository import \
    DeadManConfigurationRepository
from data.dead_man_switch_repository import DeadManSwitchRepository
from domain.exceptions import (SwitchConfigurationNotFoundException,
                               SwitchExistsException, SwitchNotFoundException)
from domain.features import Feature
from domain.health import DeadManSwitch, DeadManSwitchConfiguration
from domain.rest import (CreateDeadManConfigurationRequest,
                         CreateSwitchRequest, DisarmSwitchRequest,
                         UpdateDeadManConfigurationRequest)

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
        configuration_id: str,
        include_switches=False
    ) -> DeadManSwitchConfiguration:

        ArgumentNullException.if_none_or_whitespace(
            configuration_id, 'configuration_id')

        logger.info(f'Get configuration: {configuration_id}')

        entity = await self.__config_repository.get({
            'configuration_id': configuration_id
        })

        if entity is None:
            logger.info(f'No configuration found: {configuration_id}')
            raise SwitchConfigurationNotFoundException(
                configuration_id=configuration_id)

        configuration = DeadManSwitchConfiguration.from_entity(
            data=entity)

        if include_switches:
            logger.info(f'Fetching mapped switches for configuration')
            switch_entities = await self.__switch_repository.get_switches_by_configuration_id(
                configuration_id=configuration_id)

            switches = [DeadManSwitch.from_entity(data=entity)
                        for entity in switch_entities]

            logger.info(f'Parsed switches: {len(switches)}')
            configuration.switches = switches

        return configuration

    async def get_configurations(
        self,
        include_switches=False
    ) -> List[DeadManSwitchConfiguration]:

        entities = await self.__config_repository.get_all()
        logger.info(f'Switch configurations fetched: {len(entities)}')

        configurations = [DeadManSwitchConfiguration.from_entity(data=entity)
                          for entity in entities]

        if include_switches:
            logger.info(f'Fetching switches for configurations')

            configuration_ids = [config.configuration_id
                                 for config in configurations]

            # Get a lookup of switches by configuration ID
            configuration_switches = await self.__get_switches_by_configuration(
                configuration_ids=configuration_ids)

            # Map the switches back to their configs
            for configuration in configurations:
                logger.info(
                    f'Mapping switches to config: {configuration.configuration_id}')
                configuration.switches = configuration_switches.get(
                    configuration.configuration_id)

        return configurations

    async def poll_switches(
        self
    ):
        poll_time = datetime.utcnow()
        logger.info(f'Poll time: {poll_time.isoformat()}')

        entities = await self.__switch_repository.get_active_switches()

        # If there are no existing active switches
        if (entities is None or not any(entities)):
            return list()

        logger.info(f'Active switch entities fetched: {len(entities)}')

        switches = [
            DeadManSwitch.from_entity(data=entity)
            for entity in entities
        ]

        configs = await self.__get_configurations_by_switches(
            switches=switches)

        triggered = list()

        for switch in switches:
            logger.info(f'Evaluating switch: {switch.switch_name}')

            configuration = configs.get(switch.configuration_id)
            switch.configuration = configuration

            if switch.last_message is None:
                logger.info(f'Switch is not initialized: {switch.switch_name}')
                continue

            max_interval = configuration.interval_hours * 60 * 60
            logger.info(f'Max interval: {max_interval}')

            interval_delta = (poll_time - switch.last_message)
            interval_seconds = interval_delta.seconds
            logger.info(f'Current interval: {interval_seconds}')

            if interval_seconds > max_interval:
                logger.info('Switch triggered with response required')
                triggered.append(switch)

            # TODO: Handle overdue 'dead' switches and consequences

        return triggered

    async def __get_configurations_by_switches(
        self,
        switches: Dict[str, DeadManSwitch]
    ) -> Dict[str, DeadManSwitchConfiguration]:

        ArgumentNullException.if_none(switches, 'switches')

        results = dict()
        get_configs = TaskCollection()

        # Get all distinct configurations for active switches
        configuration_ids = list(set([switch.configuration_id
                                 for switch in switches]))
        logger.info(f'Distinct configs: {configuration_ids}')

        async def __get_configuration(
            configuration_id: str
        ):
            logger.info(f'Fetching mapped configuration: {configuration_id}')
            entity = await self.__config_repository.get({
                'configuration_id': configuration_id
            })

            config = DeadManSwitchConfiguration.from_entity(
                data=entity)

            results[configuration_id] = config

        for configuration_id in configuration_ids:
            get_configs.add_task(
                __get_configuration(
                    configuration_id=configuration_id))

        await get_configs.run()

        return results

    async def __get_switches_by_configuration(
        self,
        configuration_ids: List[str]
    ) -> Dict[str, DeadManSwitch]:

        ArgumentNullException.if_none(
            configuration_ids,
            'configuration_ids')

        get_switches = TaskCollection()
        results = dict()

        async def __get_configuration_switches(
            configuration_id: str
        ):
            logger.info(
                f'Fetching switches for configuration: {configuration_id}')

            entities = await self.__switch_repository.get_switches_by_configuration_id(
                configuration_id=configuration_id)

            switches = [DeadManSwitch.from_entity(data=entity)
                        for entity in entities]

            results[configuration_id] = switches

        for configuration_id in configuration_ids:
            get_switches.add_task(
                __get_configuration_switches(
                    configuration_id=configuration_id))

        await get_switches.run()

        logger.info(f'Switches by configuration: {results}')
        return results

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

    async def __is_feature_enabled(
        self
    ) -> bool:

        if not await self.__feature_client.is_enabled(
                feature_key=Feature.DeadManSwitch):

            logger.info(f'Feature is disabled: {Feature.DeadManSwitch}')
            return False
        return True
