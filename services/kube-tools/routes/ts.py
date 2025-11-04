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


@ts_bp.configure('/api/ts/backfill', methods=['POST'])
async def backfill_posts(container):
    """
    Backfill Truth Social posts from RSS feed to database.

    Query params:
        process_summaries: bool (default: true) - Whether to generate AI summaries
    """
    service: TruthSocialPushService = container.resolve(TruthSocialPushService)

    process_summaries = request.args.get('process_summaries', 'true').lower() == 'true'

    logger.info(f"Starting backfill with process_summaries={process_summaries}")
    stats = await service.backfill_posts(process_summaries=process_summaries)

    return {
        'success': True,
        'message': 'Backfill completed',
        'stats': stats
    }
