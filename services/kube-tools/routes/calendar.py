from domain.auth import AuthPolicy
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.calendar_service import CalendarService

calendar_bp = MetaBlueprint('calendar_bp', __name__)


def get_calendar_events_params() -> dict:
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    return {
        'start_date': start_date,
        'end_date': end_date
    }


@calendar_bp.configure('/api/calendar/events', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_calendar_events(container):
    service: CalendarService = container.resolve(CalendarService)

    params = get_calendar_events_params()

    result = await service.get_calendar_events(
        **params)

    return result


@calendar_bp.configure('/api/calendar/sync', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def sync_calendar_events(container):
    service: CalendarService = container.resolve(CalendarService)

    return await service.sync_calendar_events()
