from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.auth import AuthPolicy
from services.calendar_service import CalendarService

calendar_bp = MetaBlueprint('calendar_bp', __name__)


@calendar_bp.configure('/api/calendar/events', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_calendar_events(container):
    service: CalendarService = container.resolve(CalendarService)

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    result = await service.get_calendar_events(
        start_date=start_date,
        end_date=end_date)

    return result
