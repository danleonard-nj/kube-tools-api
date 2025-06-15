from pydantic import BaseModel
from domain.auth import AuthPolicy
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from models.calendar_models import GoogleCalendarEvent
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


class CalendarEventPromptRequest(BaseModel):
    prompt: str


@calendar_bp.configure('/api/calendar/prompt', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_calendar_prompt(container):
    service: CalendarService = container.resolve(CalendarService)

    data = await request.get_json()

    model = CalendarEventPromptRequest.model_validate(data)

    result = await service.generate_calendar_json_from_prompt(
        prompt=model.prompt)

    return result.model_dump()


@calendar_bp.configure('/api/calendar/save', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def post_calendar_save(container):
    service: CalendarService = container.resolve(CalendarService)

    data = await request.get_json()

    model = GoogleCalendarEvent.model_validate(data)

    result = await service.create_calendar_event(
        event=model)

    return result
