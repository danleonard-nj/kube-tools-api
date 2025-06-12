from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import OpenAuthBlueprint
from services.android_service import AndroidService
from quart import request

logger = get_logger(__name__)

android_bp = OpenAuthBlueprint('android_bp', __name__)


@android_bp.configure('/api/android/network', methods=['POST'])
async def post_network(container):
    service: AndroidService = container.resolve(AndroidService)

    data = await request.get_json()

    return await service.capture_network_diagnostics(
        network_diagnostics=data)
