from datetime import datetime, timedelta
from framework.di.service_provider import ServiceProvider
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from clients.nest_client import NestClient
from domain.auth import AuthPolicy
from domain.rest import NestCommandRequest, NestSensorDataRequest
from services.nest_command_service import NestCommandService
from services.nest_service import NestService


logger = get_logger(__name__)

nest_bp = MetaBlueprint('nest_bp', __name__)


def default_start_timestamp():
    date = datetime.utcnow() - timedelta(days=7)
    return int(date.timestamp())


@nest_bp.configure('/api/nest/auth', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_auth_creds(container: ServiceProvider):
    service: NestClient = container.resolve(NestClient)

    token = await service.get_token()

    return {
        'token': token
    }


@nest_bp.configure('/api/nest/thermostat', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_thermostat(container: ServiceProvider):
    service: NestService = container.resolve(NestService)

    return await service.get_thermostat()


@nest_bp.configure('/api/nest/sensor/purge', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_sensor_purge(container: ServiceProvider):
    service: NestService = container.resolve(NestService)

    return await service.purge_sensor_data()


@nest_bp.with_key_auth('/api/nest/sensor', methods=['POST'], key_name='nest-sensor-api-key')
async def post_sensor_data(container: ServiceProvider):
    service: NestService = container.resolve(NestService)

    body = await request.get_json()

    logger.info(f'Body: {body}')

    sensor_request = NestSensorDataRequest(
        data=body)

    return await service.log_sensor_data(
        sensor_request=sensor_request)


@nest_bp.configure('/api/nest/sensor', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_sensor_data(container: ServiceProvider):
    service: NestService = container.resolve(NestService)

    start_timestamp = request.args.get(
        'start_timestamp',
        default_start_timestamp())

    return await service.get_sensor_data(
        start_timestamp=start_timestamp)


@nest_bp.configure('/api/nest/sensor/grouped', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_grouped_sensor_data(container: ServiceProvider):
    service: NestService = container.resolve(NestService)

    start_timestamp = request.args.get(
        'start_timestamp',
        default_start_timestamp())

    return await service.get_grouped_sensor_data(
        start_timestamp=start_timestamp)


@nest_bp.configure('/api/nest/sensor/info', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_sensor_info(container: ServiceProvider):
    service: NestService = container.resolve(NestService)

    start_timestamp = request.args.get(
        'start_timestamp',
        default_start_timestamp())

    return await service.get_sensor_info()


@nest_bp.configure('/api/nest/sensor/info/poll', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def get_sensor_info_poll(container: ServiceProvider):
    service: NestService = container.resolve(NestService)

    return await service.poll_sensor_status()


@nest_bp.configure('/api/nest/command', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_command(container: ServiceProvider):
    service: NestCommandService = container.resolve(NestCommandService)

    body = await request.get_json()

    command_request = NestCommandRequest(
        data=body)

    return await service.handle_command(
        command_type=command_request.command_type,
        params=command_request.params)
