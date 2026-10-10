"""Entries: searching, reading, creating and titling them."""

from __future__ import annotations

from typing import Annotated, List, Optional

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from domain.journal import JournalSource
from mcp_server.models import Entry, EntrySearch, EntryWrite
from mcp_server.tools.common import (
    EndDate,
    EntryId,
    InvalidArgument,
    Principal,
    StartDate,
    ToolRunner,
    as_list,
    check_offset,
    clamp_limit,
    require_entry_id,
    resolve_range,
    utc_bounds,
)
from mcp_server.views import entry_summary, full_entry
from services.journal_service import JournalService

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
CREATES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
UPDATES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

MAX_TEXT_LENGTH = 20000
MAX_TITLE_LENGTH = 120


def register(server: MCPServer, runner: ToolRunner) -> None:
    name = runner.config.tool_name
    zone = runner.config.zone
    time_zone = runner.config.time_zone

    @server.tool(
        name=name('search_entries'),
        title='Search journal entries',
        description=(
            'Find journal entries, newest first, as short rows: date, title, tags, mood, '
            'one-line summary and word count. Filter by date range, by tags (an entry must '
            'carry all of them) and by text, which matches words or a phrase anywhere in the '
            'title, transcript or summaries and returns a snippet around the match. With no '
            'filters it lists the most recent entries. Use get_entry for an entry\'s full text '
            'and analysis.'
        ),
        annotations=READ_ONLY,
    )
    async def search_entries(
        start_date: StartDate = None,
        end_date: EndDate = None,
        tags: Annotated[Optional[List[str]], Field(
            default=None, description='Only entries carrying every one of these tags.')] = None,
        text: Annotated[Optional[str], Field(
            default=None, description='A word or phrase to find; matched literally, ignoring case.')] = None,
        limit: Annotated[int, Field(description='Entries per page, at most 100.')] = 20,
        offset: Annotated[int, Field(description='Entries to skip, for paging.')] = 0,
    ) -> EntrySearch:
        async def operation(_: Principal) -> EntrySearch:
            start, end = resolve_range(start_date, end_date, zone, default_days=None)
            start_utc, end_utc = utc_bounds(start, end, zone)
            page_size = clamp_limit(limit)
            skip = check_offset(offset)
            query = (text or '').strip() or None

            docs, total = await runner.resolve(JournalService).search_entries(
                start=start_utc, end=end_utc, tags=as_list(tags), text=query,
                limit=page_size, offset=skip)
            return EntrySearch(
                entries=[entry_summary(doc, zone, query) for doc in docs],
                total=total,
                offset=skip,
                limit=page_size,
                has_more=skip + len(docs) < total,
                time_zone=time_zone,
            )

        return await runner.run('search_entries', operation)

    @server.tool(
        name=name('get_entry'),
        title='Read a journal entry',
        description=(
            'One journal entry in full: the transcript in the user\'s own words (cleaned up '
            'when available), and its analysis -- summaries, key events, people, places, '
            'stressors, positive developments, open loops, themes, mood, symptoms and action '
            'items -- plus tags and attachment names.'
        ),
        annotations=READ_ONLY,
    )
    async def get_entry(entry_id: EntryId) -> Entry:
        async def operation(_: Principal) -> Entry:
            wanted = require_entry_id(entry_id)
            service = runner.resolve(JournalService)
            doc = await service.get_entry(wanted)
            if doc is None:
                raise InvalidArgument(f'No journal entry has entry_id {wanted!r}.')
            attachments = await service.list_attachments(wanted) or []
            return full_entry(doc, attachments, zone, time_zone)

        return await runner.run('get_entry', operation)

    @server.tool(
        name=name('create_entry'),
        title='Add a journal entry',
        description=(
            'Add a new text journal entry, dated now. Only use this when the user asks to add '
            'something to their journal, and write it in their words. A title is generated '
            'when none is given, and the entry is queued for analysis (summary, mood, themes), '
            'which completes shortly after. Prefer existing tags (see list_tags).'
        ),
        annotations=CREATES,
    )
    async def create_entry(
        text: Annotated[str, Field(description='The entry text, first person, as the user would write it.')],
        title: Annotated[Optional[str], Field(
            default=None, description='Optional title; leave empty to have one generated.')] = None,
        tags: Annotated[Optional[List[str]], Field(default=None, description='Optional tags.')] = None,
    ) -> EntryWrite:
        async def operation(principal: Principal) -> EntryWrite:
            body = (text or '').strip()
            if not body:
                raise InvalidArgument('text must not be empty.')
            if len(body) > MAX_TEXT_LENGTH:
                raise InvalidArgument(f'text is limited to {MAX_TEXT_LENGTH} characters.')
            heading = (title or '').strip() or None
            if heading and len(heading) > MAX_TITLE_LENGTH:
                raise InvalidArgument(f'title is limited to {MAX_TITLE_LENGTH} characters.')

            created = await runner.resolve(JournalService).create_entry({
                'raw_transcript': body,
                'title': heading,
                'tags': as_list(tags),
                'source': JournalSource.TEXT,
            })
            return EntryWrite(
                entry=entry_summary(created, zone),
                message='Entry added. Analysis is queued and will be available from get_entry shortly.')

        return await runner.run('create_entry', operation, write=True)

    @server.tool(
        name=name('set_title'),
        title='Retitle a journal entry',
        description=(
            'Set an entry\'s title. A title set here is kept: it is never replaced by a '
            'generated one.'
        ),
        annotations=UPDATES,
    )
    async def set_title(
        entry_id: EntryId,
        title: Annotated[str, Field(description='The new title.')],
    ) -> EntryWrite:
        async def operation(principal: Principal) -> EntryWrite:
            wanted = require_entry_id(entry_id)
            heading = (title or '').strip()
            if not heading:
                raise InvalidArgument('title must not be empty.')
            if len(heading) > MAX_TITLE_LENGTH:
                raise InvalidArgument(f'title is limited to {MAX_TITLE_LENGTH} characters.')

            updated = await runner.resolve(JournalService).set_title(wanted, heading)
            if updated is None:
                raise InvalidArgument(f'No journal entry has entry_id {wanted!r}.')
            return EntryWrite(entry=entry_summary(updated, zone), message='Title updated.')

        return await runner.run('set_title', operation, write=True)
