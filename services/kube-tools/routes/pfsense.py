from framework.di.service_provider import ServiceProvider
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from services.pfsense_log_service import PfSenseLogService

logger = get_logger(__name__)

pfsense_bp = MetaBlueprint('pfsense_bp', __name__)

API_KEY_NAME = 'pfsense-log-ingestion-key'


@pfsense_bp.with_key_auth('/api/pfsense/log', methods=['POST'], key_name=API_KEY_NAME)
async def post_pfsense_log(container: ServiceProvider):
    service: PfSenseLogService = container.resolve(PfSenseLogService)

    body = await request.get_json()

    return await service.capture_log(
        log=body)
