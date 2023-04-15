from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.auth import AuthPolicy
from domain.rest import (CreateDeadManConfigurationRequest,
                         CreateSwitchRequest, DisarmSwitchRequest,
                         UpdateDeadManConfigurationRequest)
from services.dead_man_switch_service import DeadManSwitchService
from utilities.utils import parse_bool

health_bp = MetaBlueprint('health_bp', __name__)

logger = get_logger(__name__)


@health_bp.configure('/api/health/dms/configuration', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_configuration(container):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    body = await request.get_json()

    configuration_request = CreateDeadManConfigurationRequest(
        data=body)

    return await service.create_configuration(
        request=configuration_request)


@health_bp.configure('/api/health/dms/configuration', methods=['PUT'], auth_scheme=AuthPolicy.Default)
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

    include_switches = request.args.get(
        'include_switches')

    return await service.get_configurations(
        include_switches=parse_bool(
            value=include_switches))


@health_bp.configure('/api/health/dms/configuration/<configuration_id>', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_configuration(container, configuration_id: str):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    include_switches = request.args.get(
        'include_switches')

    return await service.get_configuration(
        configuration_id=configuration_id,
        include_switches=parse_bool(
            value=include_switches))


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


@health_bp.configure('/api/health/dms/switch/poll', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_switch_poll(container):
    service: DeadManSwitchService = container.resolve(
        DeadManSwitchService)

    return await service.poll_switches()
