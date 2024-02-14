

import calendar
import json
from math import e
import stat
from typing import Dict
from data.google.google_calendar_repository import GooleCalendarEventRepository
from domain.calendar import CalendarEvent
from services.google_auth_service import GoogleAuthService
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from framework.serialization import Serializable
from framework.crypto.hashing import sha256
from datetime import datetime, timedelta
from dateutil import parser
from framework.utilities.iter_utils import first

logger = get_logger(__name__)

GOOGLE_CALENDAR_SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']


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
        self._repository = repository

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

        events = [CalendarEvent.from_event(event) for event in events]

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
