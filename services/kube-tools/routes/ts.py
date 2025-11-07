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


@ts_bp.configure('/api/ts/posts', methods=['GET'])
async def get_saved_posts(container):
    """
    Get saved Truth Social posts from database.

    Query params:
        limit: int (default: 10) - Maximum number of posts to return
        start_timestamp: int (optional) - Start of timestamp range (Unix timestamp)
        end_timestamp: int (optional) - End of timestamp range (Unix timestamp)
    """
    service: TruthSocialPushService = container.resolve(TruthSocialPushService)

    limit = int(request.args.get('limit', 10))
    start_timestamp = request.args.get('start_timestamp')
    end_timestamp = request.args.get('end_timestamp')

    # Convert to int if provided
    if start_timestamp:
        start_timestamp = int(start_timestamp)
    if end_timestamp:
        end_timestamp = int(end_timestamp)

    return await service.get_saved_posts(
        limit=limit,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp
    )


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
