from pydantic import BaseModel, Field, HttpUrl, EmailStr
from typing import List, Optional, Literal, Dict


class CalendarConfig(BaseModel):
    preferences: Dict[str, str] = None


class EventDateTime(BaseModel):
    dateTime: str  # ISO 8601 format
    timeZone: str  # e.g., "America/New_York"


class Attendee(BaseModel):
    email: EmailStr
    displayName: Optional[str] = None
    optional: Optional[bool] = None
    responseStatus: Optional[Literal["accepted", "declined", "tentative", "needsAction"]] = None


class ReminderOverride(BaseModel):
    method: Literal["email", "popup"]
    minutes: int


class Reminders(BaseModel):
    useDefault: bool
    overrides: Optional[List[ReminderOverride]] = None


class ConferenceSolutionKey(BaseModel):
    type: Literal["eventHangout", "hangoutsMeet"]


class CreateRequest(BaseModel):
    requestId: str
    conferenceSolutionKey: ConferenceSolutionKey


class ConferenceData(BaseModel):
    createRequest: CreateRequest


class ExtendedProperties(BaseModel):
    private: Optional[Dict[str, str]] = None
    shared: Optional[Dict[str, str]] = None


class Source(BaseModel):
    title: str
    url: HttpUrl


class GoogleCalendarEvent(BaseModel):
    summary: str
    location: Optional[str] = None
    description: Optional[str] = None
    start: EventDateTime
    end: EventDateTime
    recurrence: Optional[List[str]] = None
    attendees: Optional[List[Attendee]] = None
    reminders: Optional[Reminders] = None
    conferenceData: Optional[ConferenceData] = None
    colorId: Optional[str] = None
    visibility: Optional[Literal["default", "public", "private"]] = None
    transparency: Optional[Literal["opaque", "transparent"]] = None
    guestsCanInviteOthers: Optional[bool] = None
    guestsCanModify: Optional[bool] = None
    guestsCanSeeOtherGuests: Optional[bool] = None
    status: Optional[Literal["confirmed", "tentative", "cancelled"]] = None
    extendedProperties: Optional[ExtendedProperties] = None
    source: Optional[Source] = None
