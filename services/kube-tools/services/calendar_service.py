from datetime import datetime
from enum import StrEnum
from typing import Optional

from clients.gpt_client import GPTClient, GptResponseToolType
from data.google.google_calendar_repository import GooleCalendarEventRepository
from dateutil import parser
from domain.calendar import SAMPLE_CALENDAR_EVENT_JSON
from domain.gpt import GPTModel
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from models.calendar_models import (Attendee, CalendarConfig,
                                    GoogleCalendarEvent, ReminderOverride,
                                    Reminders)
from services.google_auth_service import GoogleAuthService
from framework.clients.feature_client import FeatureClientAsync
from utilities.utils import strip_json_backticks

logger = get_logger(__name__)


class EventColor(StrEnum):
    BLUE = "7"


def ensure_datetime(
    value: datetime | str
) -> datetime:
    if isinstance(value, datetime):
        return value

    return parser.parse(value)


def _get_system_prompt() -> str:
    return f'''You are a helpful assistant that generates JSON Google Calendar events based on user input.
Your task is to create a JSON object that represents a Google Calendar event.
If the location provided is vague or incomplete, use web_search to resolve the full address.
Try to get the most granular address possible (e.g., full venue address).

The JSON object must look exactly like this:
{SAMPLE_CALENDAR_EVENT_JSON}

Respond ONLY with a JSON object. DO NOT include markdown formatting, commentary, headings, or explanations.
The first character must be '{{' and the last character must be '}}'.'''


def _get_user_prompt(locality: str, text: str = None, has_image: bool = False) -> str:
    event_text = f"Event: {text}\n" if text else ""
    image_instruction = "\nIf an image is provided, extract all relevant event details from it." if has_image else ""

    return f"""Create a Google Calendar event from the following details:

{event_text}User locality: {locality}
Current date and time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Instructions:
- Use a descriptive title for the event
- Include additional user requests in the description field
- For recurrence, use RRULE format (search if unsure of syntax)
- Output ONLY the JSON object{image_instruction}"""


class CalendarService:
    def __init__(
        self,
        auth_service: GoogleAuthService,
        repository: GooleCalendarEventRepository,
        gpt_client: GPTClient,
        config: CalendarConfig,
        feature_client: FeatureClientAsync
    ):
        self._auth_service = auth_service
        self._repository = repository
        self._gpt_client = gpt_client
        self._feature_client = feature_client

        self._config = config

    async def _get_calendar_event_gpt_model(self):
        return await self._feature_client.is_enabled('gpt-model-calendar-event-service')

    async def create_calendar_event(
        self,
        event: GoogleCalendarEvent
    ) -> dict:
        ArgumentNullException.if_none(event, 'event')

        logger.info(f'Creating calendar event: {event.summary}')
        service = await self.get_calendar_client()

        # Convert the Pydantic model to a dict, excluding unset/null fields
        event_dict = event.model_dump(exclude_none=True)

        # Insert the event into the primary calendar
        created_event = service.events().insert(
            calendarId='primary',
            body=event_dict,
            sendUpdates='all',
        ).execute()

        logger.info(f'Event created: {created_event.get("id")}, summary: {created_event.get("summary")})')
        return created_event

    async def get_calendar_client(self):
        logger.info('Fetching calendar client')
        auth = await self._auth_service.get_credentials(
            client_name='calendar-client',
            scopes=['https://www.googleapis.com/auth/calendar.events']
        )

        return build("calendar", "v3", credentials=auth)

    async def get_calendar_events(
        self,
        start_date: str | datetime,
        end_date: str | datetime
    ) -> list[dict]:
        ArgumentNullException.if_none(start_date, 'start_date')
        ArgumentNullException.if_none(end_date, 'end_date')

        logger.info(
            f'Fetching calendar events from {start_date} to {end_date}')

        start_date = ensure_datetime(start_date)
        end_date = ensure_datetime(end_date)

        service = await self.get_calendar_client()

        events_result = service.events().list(
            calendarId='primary',
            timeMin=f'{start_date.isoformat()}Z',
            timeMax=f'{end_date.isoformat()}Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        return [GoogleCalendarEvent.model_validate(event).model_dump() for event in events]

    def _populate_event_defaults(self, event: GoogleCalendarEvent) -> GoogleCalendarEvent:
        event.attendees = [
            Attendee(
                email=self._config.preferences.get('email'),
                displayName=self._config.preferences.get('name'),
                optional=False,
                responseStatus='accepted'
            )
        ]
        event.reminders = Reminders(
            useDefault=False,
            overrides=[
                ReminderOverride(method='popup', minutes=15),
                ReminderOverride(method='popup', minutes=60),
                ReminderOverride(method='popup', minutes=60 * 24),
            ]
        )
        event.colorId = EventColor.BLUE
        return event

    async def create_event_from_input(
        self,
        prompt: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        text: Optional[str] = None
    ) -> dict:
        """Create a calendar event from a prompt, an image, or both."""
        if not prompt and not image_bytes:
            return {"error": "No valid input provided. Supply either image_bytes or prompt."}

        locality = self._config.preferences.get('home', 'New Jersey')
        model = (await self._get_calendar_event_gpt_model()) or GPTModel.GPT_4_1_MINI

        system_prompt = _get_system_prompt()
        user_prompt = _get_user_prompt(locality, text or prompt, has_image=bool(image_bytes))

        logger.info(f'Creating calendar event with model: {model}')

        # Generate response with or without image
        if image_bytes:
            result = await self._gpt_client.generate_response_with_image_and_tools(
                image_bytes=image_bytes,
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=model,
                custom_tools=[{'type': GptResponseToolType.WEB_SEARCH_PREVIEW}]
            )
        else:
            result = await self._gpt_client.generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=model,
                custom_tools=[{'type': GptResponseToolType.WEB_SEARCH_PREVIEW}]
            )

        logger.info(f'Used {result.usage} tokens with model {model}')

        # Parse and populate defaults
        response_text = strip_json_backticks(result.text)
        event_data = GoogleCalendarEvent.model_validate_json(response_text, strict=True)
        self._populate_event_defaults(event_data)

        return event_data.model_dump()
