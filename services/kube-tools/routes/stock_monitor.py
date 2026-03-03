from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from services.stock_monitor_service import StockMonitorService

logger = get_logger(__name__)

stock_monitor_bp = MetaBlueprint('stock_monitor_bp', __name__)


@stock_monitor_bp.configure('/api/stock/monitor/poll', methods=['POST'], auth_scheme='default')
async def post_stock_monitor_poll(container):
    """Poll endpoint called by scheduler every 5 minutes.

    Accepts optional JSON body to override config thresholds:
    {
        "sell_threshold": 375,
        "floor_threshold": 300,
        "swing_percent": 0.05
    }
    """
    service: StockMonitorService = container.resolve(StockMonitorService)

    body = await request.get_json(silent=True) or {}

    logger.info(f'Received stock monitor poll request with body: {body}')

    sell_threshold = body.get('sell_threshold')
    floor_threshold = body.get('floor_threshold')
    swing_percent = body.get('swing_percent')

    # Coerce to float if provided
    if sell_threshold is not None:
        sell_threshold = float(sell_threshold)
    if floor_threshold is not None:
        floor_threshold = float(floor_threshold)
    if swing_percent is not None:
        swing_percent = float(swing_percent)

    result = await service.poll(
        sell_threshold=sell_threshold,
        floor_threshold=floor_threshold,
        swing_percent=swing_percent)

    return result
