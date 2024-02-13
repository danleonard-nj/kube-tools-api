from datetime import datetime
from typing import Tuple

from domain.auth import AuthPolicy
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.api_event_service import ApiEventHistoryService

api_event_history_bp = MetaBlueprint('api_event_history_bp', __name__)


def get_event_history_args() -> Tuple[int, int]:
    return (
        int(request.args.get('start_timestamp')),
        int(request.args.get('end_timestamp', datetime.now().timestamp())),
        request.args.get('include_body', 'false') == 'true'
    )


@api_event_history_bp.configure('/api/logs/events', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_event_history(container):
    service: ApiEventHistoryService = container.resolve(
        ApiEventHistoryService)

    start, end, include_body = get_event_history_args()

    return await service.get_api_event_history(
        start_timestamp=start,
        end_timestamp=end,
        include_body=include_body)
