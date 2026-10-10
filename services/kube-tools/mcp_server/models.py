"""Result shapes for the MCP tools.

Every tool returns one of these, never a raw Mongo document. The models are the
allowlist: they are built field by field in ``mcp_server.views``, and
``extra='ignore'`` drops anything else, so processing errors, LLM usage
records, pre-polish text, segments, GridFS ids, the risk-flag classifier, or
anything added to a journal document later cannot reach a client by being
present on it. Add a field here deliberately or it does not leave the server.

Dates are days in the journal's time zone (``mcp.time_zone``), not UTC.
"""

from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra='ignore', populate_by_name=True)


def _str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


StrList = Annotated[List[str], BeforeValidator(_str_list)]
LocalDate = Annotated[Optional[str], Field(description='Day in the journal\'s time zone, YYYY-MM-DD.')]


# -- Tags -------------------------------------------------------------------


class TagCount(_Model):
    tag: str
    entry_count: int = Field(description='Entries carrying this tag.')


class TagList(_Model):
    tags: List[TagCount] = Field(description='Every tag in use, most used first.')


class TagUpdate(_Model):
    entry_id: str
    tags: StrList = Field(description='The entry\'s tags after the change.')
    added: StrList = Field(description='Tags that were not on the entry before.')
    removed: StrList = Field(description='Tags that were on the entry and are now gone.')
    new_tags: StrList = Field(description='Added tags not used on any other entry until now.')


# -- Entries ----------------------------------------------------------------


class Mood(_Model):
    score: Optional[int] = Field(None, description='1 (very low) to 10 (very good).')
    label: Optional[str] = None


class EntrySummary(_Model):
    entry_id: str
    date: LocalDate = None
    recorded_at: Optional[str] = Field(None, description='Local time the entry was recorded, ISO 8601 with offset.')
    title: Optional[str] = None
    tags: StrList = Field(default_factory=list)
    source: Optional[str] = Field(None, description='voice (dictated and transcribed) or text.')
    status: Optional[str] = Field(
        None, description='processed once analysis has run; queued or processing before; failed if it did not.')
    mood: Optional[Mood] = None
    summary: Optional[str] = Field(None, description='One-line summary from the analysis.')
    word_count: int = 0
    snippet: Optional[str] = Field(None, description='Text around the first match, when searching by text.')


class EntrySearch(_Model):
    entries: List[EntrySummary] = Field(description='Newest first.')
    total: int = Field(description='Entries matching the filters, across all pages.')
    offset: int
    limit: int
    has_more: bool
    time_zone: str


class Analysis(_Model):
    summary_short: Optional[str] = None
    summary_detailed: Optional[str] = None
    key_events: StrList = Field(default_factory=list)
    people_mentioned: StrList = Field(default_factory=list)
    places_or_contexts: StrList = Field(default_factory=list)
    stressors: StrList = Field(default_factory=list)
    positive_developments: StrList = Field(default_factory=list)
    open_loops: StrList = Field(default_factory=list)
    themes: StrList = Field(default_factory=list)
    mood: Optional[Mood] = None
    symptoms: StrList = Field(default_factory=list)
    action_items: StrList = Field(default_factory=list)


class Attachment(_Model):
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None


class Entry(_Model):
    entry_id: str
    date: LocalDate = None
    recorded_at: Optional[str] = Field(None, description='Local time the entry was recorded, ISO 8601 with offset.')
    title: Optional[str] = None
    title_is_manual: bool = Field(False, description='True when the user set the title rather than it being generated.')
    tags: StrList = Field(default_factory=list)
    source: Optional[str] = None
    status: Optional[str] = None
    transcript: str = Field('', description='The entry text, in the user\'s own words.')
    transcript_is_cleaned: bool = Field(
        False, description='True when this is the cleaned-up transcript rather than the raw dictation.')
    word_count: int = 0
    analysis: Optional[Analysis] = Field(None, description='Absent until analysis has run.')
    attachments: List[Attachment] = Field(default_factory=list)
    time_zone: str


class EntryWrite(_Model):
    entry: EntrySummary
    message: str


# -- Stats ------------------------------------------------------------------


class LabelCount(_Model):
    label: str
    count: int


class ThemeCount(LabelCount):
    last_seen: LocalDate = None


class MoodDay(_Model):
    date: str
    score: float = Field(description='Average mood score of that day\'s entries.')
    entries: int


class OpenItem(_Model):
    kind: Literal['action_item', 'open_loop']
    text: str
    date: LocalDate = None
    entry_id: Optional[str] = None


class JournalStats(_Model):
    start_date: str
    end_date: str
    time_zone: str
    entry_count: int
    truncated: bool = Field(description='True when the range held more entries than were counted.')
    entries_awaiting_analysis: int
    days_with_entries: int
    longest_streak_days: int = Field(description='Longest run of consecutive days with an entry, within the range.')
    streak_at_end_days: int = Field(
        description='Consecutive days with an entry ending on end_date (or the day before).')
    mood_average: Optional[float] = None
    mood_daily: List[MoodDay] = Field(default_factory=list)
    themes: List[ThemeCount] = Field(default_factory=list)
    people: List[LabelCount] = Field(default_factory=list)
    stressors: List[LabelCount] = Field(default_factory=list)
    open_items: List[OpenItem] = Field(
        default_factory=list, description='Action items and open loops, newest entry first.')
    open_items_total: int = 0
