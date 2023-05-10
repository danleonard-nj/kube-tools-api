from framework.di.service_provider import ServiceProvider
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from clients.nest_client import NestClient
from domain.auth import AuthPolicy
from domain.rest import NestSensorDataRequest
from services.nest_service import NestService

logger = get_logger(__name__)

nest_bp = MetaBlueprint('nest_bp', __name__)


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

    sensor_request = NestSensorDataRequest(
        data=body)

    return await service.log_sensor_data(
        sensor_request=sensor_request)
