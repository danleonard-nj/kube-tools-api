from datetime import datetime, timedelta
from typing import Optional

from clients.gpt_client import GPTClient, GptResponseToolType
from data.google.google_calendar_repository import GooleCalendarEventRepository
from dateutil import parser
from domain.calendar import SAMPLE_CALENDAR_EVENT_JSON, CalendarEvent
from domain.gpt import GPTModel
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from models.calendar_models import (Attendee, CalendarConfig,
                                    GoogleCalendarEvent, ReminderOverride,
                                    Reminders)
from services.google_auth_service import GoogleAuthService
from utilities.utils import strip_json_backticks

logger = get_logger(__name__)


def ensure_datetime(
    value: datetime | str
) -> datetime:
    if isinstance(value, datetime):
        return value

    return parser.parse(value)


def get_calendar_system_prompt(locality: str) -> str:
    return f'''
    You are a helpful assistant that generates Google Calendar events based on user input.
    Your task is to create a JSON object that represents a Google Calendar event.
    If the location provided is vague or incomplete, use web_search to resolve the full address before generating the JSON event.
    The JSON object must look exactly like this:
    {{SAMPLE_CALENDAR_EVENT_JSON}}

    Respond ONLY with a JSON object.
    DO NOT include:
    - Markdown formatting (e.g. triple backticks)
    - Commentary
    - Headings
    - Explanations
    - Anything outside the raw JSON object

    The first character of your reply must be '{{'. The last character must be '}}'. Nothing should appear before or after the JSON.
    '''


def get_calendar_user_prompt(locality: str, text: str = None, has_image: bool = False) -> str:
    event_line = f"Event: {text}\n" if text else ""
    base = (
        """
    Create a Google Calendar event from the following details:

    """
        + event_line +
        f"User locality (for search reference if search is required): {locality}\n"
        """
    The recurrence IS NOT required, BUT if the user specifies it, it SHOULD BE included in the form of an an RRULE PARAMETER.
    IF you are UNSURE of how to create an RRULE parameter, DO A WEB SEARCH to LEARN the syntax

    Instructions:
    - Fill in the JSON calendar object accordingly.
    - You MUST include the user's name/email in the attendees field.
    - You MUST add all reminder times as popup overrides.
    - Do not include recurrence, conferenceData, or unused nulls if possible.
    - Output ONLY the JSON object — no Markdown, no commentary, no headings.
    """
    )
    if has_image:
        base += '\nIf an image is provided, extract all relevant event details from the image as well as the text.'
    return base


class CalendarService:
    def __init__(
        self,
        auth_service: GoogleAuthService,
        repository: GooleCalendarEventRepository,
        gpt_client: GPTClient,
        config: CalendarConfig
    ):
        self._auth_service = auth_service
        self._repository = repository
        self._gpt_client = gpt_client

        self._config = config

    def parse_event(
        self,
        json_str: str
    ):

        event = GoogleCalendarEvent.model_validate(json_str)

    async def generate_calendar_json_from_prompt(
        self,
        prompt: str
    ) -> GoogleCalendarEvent:
        locality = self._config.preferences.get('home', 'New Jersey')
        system_prompt = get_calendar_system_prompt(locality)
        user_prompt = get_calendar_user_prompt(locality, prompt)
        result = await self._gpt_client.generate_response(
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=GPTModel.GPT_4O,
            custom_tools=[{'type': GptResponseToolType.WEB_SEARCH_PREVIEW}],
            temperature=0.0,
        )
        content = result.output[-1].content[0].text
        stripped = strip_json_backticks(content)
        model = GoogleCalendarEvent.model_validate_json(
            stripped,
            strict=True)
        model.attendees = [
            Attendee(
                email=self._config.preferences.get('email'),
                displayName=self._config.preferences.get('name'),
                optional=False
            )
        ]
        model.reminders = Reminders(
            useDefault=False,
            overrides=[
                ReminderOverride(method='popup', minutes=15),
                ReminderOverride(method='popup', minutes=60),
                ReminderOverride(method='popup', minutes=60 * 24),
            ]
        )
        return model

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

    async def get_calendar_client(
        self
    ) -> Credentials:
        logger.info(f'Fetching calendar client')
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

        # Validate and return the events
        events = [GoogleCalendarEvent.model_validate(event).model_dump() for event in events]

        return events

    async def sync_calendar_events(
        self
    ):
        logger.info(f'Syncing calendar events')

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')

        logger.info(
            f'Fetching calendar events from {start_date} to {end_date}')

        calendar_events = await self.get_calendar_events(
            start_date=start_date,
            end_date=end_date
        )

        updated = []
        insert = []

        cutoff = int((datetime.utcnow() - timedelta(days=90)).timestamp())
        for event in calendar_events:

            if event.updated_date_timestamp > cutoff:
                updated.append(event)

            if event.created_date_timestamp > cutoff:
                insert.append(event)

        comparison_records = await self._repository.collection.find(
            filter={
                'id': {
                    '$in': ([event.id for event in updated] + [event.id for event in insert])
                }
            }
        ).to_list(None)

        comparison_records = [CalendarEvent.from_entity(record)
                              for record in comparison_records]

        comparison_lookup = {
            record.id: record
            for record in comparison_records
        }

        updated_records = []
        inserted_records = []
        for record in comparison_records:
            event = comparison_lookup.get(record.id)

            if event is None:
                logger.info(f'Inserting event {record.id}')
                inserted_records.append(record)

            if event.hash != record.hash:
                logger.info(f'Updating event {event.id}')
                await self._repository.replace(
                    filter=event.get_selector(),
                    replacement=event.to_dict()
                )
                updated_records.append(event)

        return {
            'updated': updated_records,
            'insert': inserted_records
        }

    async def save_calendar_event(
        self,
        event: GoogleCalendarEvent
    ):
        """
        Save (POST) a calendar event to the user's Google Calendar.
        """
        logger.info(f'Saving calendar event: {event.summary}')
        service = await self.get_calendar_client()

        # Convert the Pydantic model to a dict, excluding unset/null fields
        event_dict = event.model_dump(exclude_none=True)

        # Insert the event into the primary calendar
        created_event = service.events().insert(
            calendarId='primary',
            body=event_dict
        ).execute()

        logger.info(f'Event created: {created_event.get("id")}, summary: {created_event.get("summary")})')
        return created_event

    async def create_event_from_image(self, image_bytes: bytes, text: Optional[str] = None) -> dict:
        """
        Process image (and optional text), send to ChatGPT, and create a calendar event.
        Accepts image as bytes (from base64 decode).
        """
        locality = self._config.preferences.get('home', 'New Jersey')
        system_prompt = get_calendar_system_prompt(locality)
        user_prompt = get_calendar_user_prompt(locality, text, has_image=True)
        gpt_result = await self._gpt_client.generate_response_with_image_and_tools(
            image_bytes=image_bytes,
            prompt=user_prompt,
            system_prompt=system_prompt,
            model=GPTModel.GPT_4O,
            temperature=0.0,
            custom_tools=[{'type': GptResponseToolType.WEB_SEARCH_PREVIEW}]
        )
        try:
            event_data = GoogleCalendarEvent.model_validate_json(gpt_result)
        except Exception as e:
            logger.error(f"Failed to parse event from GPT: {e}")
            return {"error": "Failed to parse event from GPT response."}
        created_event = await self.create_calendar_event(event_data)
        return {"event": created_event}

    def _populate_event_defaults(self, event):
        """
        Helper to set attendees and reminders on a GoogleCalendarEvent.
        """
        event.attendees = [
            Attendee(
                email=self._config.preferences.get('email'),
                displayName=self._config.preferences.get('name'),
                optional=False
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
        return event

    async def create_event_from_input(self, prompt: Optional[str] = None, image_bytes: Optional[bytes] = None, text: Optional[str] = None) -> dict:
        """
        Create a calendar event from a prompt, an image, or both.
        - If image_bytes is provided, uses image+text logic.
        - If only prompt is provided, uses prompt logic.
        - If neither, returns an error.
        """
        locality = self._config.preferences.get('home', 'New Jersey')
        if image_bytes:
            # Use image+text logic
            system_prompt = get_calendar_system_prompt(locality)
            user_prompt = get_calendar_user_prompt(locality, text or prompt, has_image=True)
            gpt_result = await self._gpt_client.generate_response_with_image_and_tools(
                image_bytes=image_bytes,
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=GPTModel.GPT_4O,
                temperature=0.0,
                custom_tools=[{'type': GptResponseToolType.WEB_SEARCH_PREVIEW}]
            )
            event_data = GoogleCalendarEvent.model_validate_json(gpt_result)
            self._populate_event_defaults(event_data)
            # created_event = await self.create_calendar_event(event_data)
            return event_data.model_dump()
        elif prompt:
            # Use prompt logic
            system_prompt = get_calendar_system_prompt(locality)
            user_prompt = get_calendar_user_prompt(locality, prompt)
            result = await self._gpt_client.generate_response(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=GPTModel.GPT_4O,
                custom_tools=[{'type': GptResponseToolType.WEB_SEARCH_PREVIEW}],
                temperature=0.0,
            )
            content = result.output[-1].content[0].text
            stripped = strip_json_backticks(content)
            model = GoogleCalendarEvent.model_validate_json(stripped, strict=True)
            self._populate_event_defaults(model)
            # created_event = await self.create_calendar_event(model)
            return model.model_dump()
        else:
            return {"error": "No valid input provided. Supply either image_bytes or prompt."}
