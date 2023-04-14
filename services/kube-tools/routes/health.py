from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.auth import AuthPolicy
from domain.rest import (CreateDeadManConfigurationRequest, CreateSwitchRequest, DisarmSwitchRequest,
                         UpdateDeadManConfigurationRequest)
from services.dead_man_switch_service import DeadManSwitchService

health_bp = MetaBlueprint('health_bp', __name__)

logger = get_logger(__name__)


@health_bp.configure('/api/health/dns/configuration', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_configuration(container):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    body = await request.get_json()

    configuration_request = CreateDeadManConfigurationRequest(
        data=body)

    return await service.create_configuration(
        request=configuration_request)


@health_bp.configure('/api/health/dns/configuration', methods=['PUT'], auth_scheme=AuthPolicy.Default)
async def put_configuration(container):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    body = await request.get_json()

    configuration_request = UpdateDeadManConfigurationRequest(
        data=body)

    return await service.update_configuration(
        request=configuration_request)


@health_bp.configure('/api/health/dms/configuration', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_configurations(container):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    return await service.get_configurations()


@health_bp.configure('/api/health/dms/configuration/<configuration_id>', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_configuration(container, configuration_id: str):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    return await service.get_configuration(
        configuration_id=configuration_id)


@health_bp.configure('/api/health/dms/switch', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_create_switch(container):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    body = await request.get_json()

    create_switch = CreateSwitchRequest(
        data=body)

    return await service.create_switch(
        request=create_switch
    )


@health_bp.configure('/api/health/dms/switch/disarm', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_disarm_switch(container):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    body = await request.get_json()

    disarm_switch = DisarmSwitchRequest(
        data=body)

    return await service.disarm_switch(
        request=disarm_switch)
