from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import OpenAuthBlueprint
from quart import request

from services.ts_push_service import TruthSocialPushService

logger = get_logger(__name__)

ts_bp = OpenAuthBlueprint('ts_bp', __name__)


@ts_bp.configure('/api/ts/latest', methods=['GET'])
async def post_network(container):
    service: TruthSocialPushService = container.resolve(TruthSocialPushService)

    return await service.get_latest_posts()
