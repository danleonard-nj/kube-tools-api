import json
from framework.serialization import Serializable
from framework.crypto.hashing import sha256
from dateutil.parser import parse


class CalendarEvent(Serializable):
    @property
    def created_date_timestamp(
        self
    ):
        return int(
            parse(self.created_date).timestamp()
        )

    @property
    def updated_date_timestamp(
        self
    ):
        return int(
            parse(self.updated_date).timestamp()
        )

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
        start_date: dict,
        end_date: dict,
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
        self.hash = self.generate_hash_key()

    def get_selector(
        self
    ):
        return {
            'id': self.id
        }

    def generate_hash_key(
        self
    ):
        data = json.dumps(self.to_dict(), default=str)
        return sha256(data)

    @staticmethod
    def from_entity(data: dict):
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
    def from_event(data: dict):
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


SAMPLE_CALENDAR_EVENT_JSON = '''
{
  "summary": "Doctor Appointment",
  "location": "Location of the event",
  "description": "Description of the event",
  "start": {
    "dateTime": "2025-06-14T18:00:00-04:00",
    "timeZone": "America/New_York"
  },
  "end": {
    "dateTime": "2025-06-14T19:00:00-04:00",
    "timeZone": "America/New_York"
  },
  "attendees": [
    { "email": "sample@sample.com", "displayName": "Sample Person", "optional": false }
  ],
  "reminders": {
    "useDefault": false,
    "overrides": [
      { "method": "popup", "minutes": 15 },
    ]
  },
  "visibility": "default",
  "status": "confirmed"
}

'''
