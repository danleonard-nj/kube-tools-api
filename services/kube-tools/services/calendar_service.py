

import json
from math import e
import stat
from typing import Dict
from data.google.google_email_repository import GooleCalendarEventRepository
from services.google_auth_service import GoogleAuthService
from framework.logger import get_logger
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from framework.serialization import Serializable
from framework.crypto.hashing import sha256
from datetime import datetime, timedelta
from dateutil import parser

logger = get_logger(__name__)

GOOGLE_CALENDAR_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


class CalendarEvent(Serializable):
    def __init__(
        self,
        id: str,
        status: str,
        link: str,
        created_date,
        updated_date,
        summary: str,
        description: str,
        event_type: str,
        location: str,
        creator: str,
        organizer: str,
        start_date: Dict,
        end_date: Dict,
        visibility: str,
        attendees: list,
        reminders: list,
        extended_properties,
        recurring_event_id: str
    ):
        self.id = id
        self.status = status
        self.link = link
        self.created_date = created_date
        self.updated_date = updated_date
        self.summary = summary
        self.description = description
        self.event_type = event_type
        self.location = location
        self.creator = creator
        self.organizer = organizer
        self.start_date = start_date
        self.end_date = end_date
        self.visibility = visibility
        self.attendees = attendees
        self.reminders = reminders
        self.extended_properties = extended_properties
        self.recurring_event_id = recurring_event_id

    def generate_hash_key(
        self
    ):
        data = json.dumps(self.to_dict(), default=str)
        return sha256(data)

    @staticmethod
    def from_entity(data: Dict):
        return CalendarEvent(
            id=data.get('id'),
            status=data.get('status'),
            link=data.get('link'),
            created_date=data.get('created_date'),
            updated_date=data.get('updated_date'),
            summary=data.get('summary'),
            description=data.get('description'),
            event_type=data.get('event_type'),
            location=data.get('location'),
            creator=data.get('creator'),
            organizer=data.get('organizer'),
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            visibility=data.get('visibility'),
            attendees=data.get('attendees'),
            reminders=data.get('reminders'),
            extended_properties=data.get('extended_properties'),
            recurring_event_id=data.get('recurring_event_id'))

    @staticmethod
    def from_event(data: Dict):
        start_date = {
            'datetime': data.get('start', dict()).get('dateTime'),
            'timezone': data.get('start', dict()).get('timeZone')
        }

        end_date = {
            'datetime': data.get('end', dict()).get('dateTime'),
            'timezone': data.get('end', dict()).get('timeZone')
        }

        return CalendarEvent(
            id=data.get('id'),
            status=data.get('status'),
            link=data.get('htmlLink'),
            created_date=data.get('created'),
            updated_date=data.get('updated'),
            summary=data.get('summary'),
            description=data.get('description'),
            event_type=data.get('eventType'),
            location=data.get('location'),
            creator=data.get('creator', dict()).get('email'),
            organizer=data.get('organizer', dict()).get('email'),
            start_date=start_date,
            end_date=end_date,
            visibility=data.get('visibility'),
            attendees=data.get('attendees'),
            reminders=data.get('reminders'),
            extended_properties=data.get('extendedProperties'),
            recurring_event_id=data.get('recurringEventId'))


def ensure_datetime(
    value: datetime | str
) -> datetime:
    if isinstance(value, datetime):
        return value

    return parser.parse(value)


class CalendarService:
    def __init__(
        self,
        auth_service: GoogleAuthService,
        repository: GooleCalendarEventRepository
    ):
        self.__auth_service = auth_service
        self.__repository = repository

    async def get_calendar_client(
        self
    ) -> Credentials:
        logger.info(f'Fetching calendar client')
        auth = await self.__auth_service.get_auth_client(
            scopes=GOOGLE_CALENDAR_SCOPES)

        return build("calendar", "v3", credentials=auth)

    async def get_calendar_events(
        self,
        start_date: str | datetime,
        end_date: str | datetime
    ):
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

        events = [CalendarEvent.from_event(event) for event in events]

        return events

    async def sync_calendar_events(
        self
    ):
        logger.info(f'Syncing calendar events')

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
