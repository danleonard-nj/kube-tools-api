"""Tags: the vocabulary entries are filed under, and changing an entry's tags."""

from __future__ import annotations

from typing import Annotated, List, Optional

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations
from pydantic import Field

from mcp_server.models import TagCount, TagList, TagUpdate
from mcp_server.tools.common import EntryId, InvalidArgument, Principal, ToolRunner, as_list, require_entry_id
from services.journal_service import JournalService

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
UPDATES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)

MAX_TAGS_PER_CALL = 20


def register(server: MCPServer, runner: ToolRunner) -> None:
    name = runner.config.tool_name

    @server.tool(
        name=name('list_tags'),
        title='Journal tags',
        description=(
            'Every tag used on journal entries, with how many entries carry each, '
            'most used first. Use it to find valid tags before filtering on them.'
        ),
        annotations=READ_ONLY,
    )
    async def list_tags() -> TagList:
        async def operation(_: Principal) -> TagList:
            counts = await runner.resolve(JournalService).list_tag_counts()
            return TagList(tags=[TagCount.model_validate(count) for count in counts])

        return await runner.run('list_tags', operation)

    @server.tool(
        name=name('update_tags'),
        title='Tag a journal entry',
        description=(
            'Add tags to and remove tags from one entry. Tags are stored lowercase. Prefer '
            'existing tags (see list_tags); the result lists any added tag that was not in '
            'use before, so a typo can be spotted and undone.'
        ),
        annotations=UPDATES,
    )
    async def update_tags(
        entry_id: EntryId,
        add: Annotated[Optional[List[str]], Field(default=None, description='Tags to add.')] = None,
        remove: Annotated[Optional[List[str]], Field(default=None, description='Tags to remove.')] = None,
    ) -> TagUpdate:
        async def operation(principal: Principal) -> TagUpdate:
            wanted = require_entry_id(entry_id)
            adding, removing = as_list(add), as_list(remove)
            if not adding and not removing:
                raise InvalidArgument('Give at least one tag to add or remove.')
            if len(adding) + len(removing) > MAX_TAGS_PER_CALL:
                raise InvalidArgument(f'At most {MAX_TAGS_PER_CALL} tags per call.')

            service = runner.resolve(JournalService)
            before = await service.get_entry(wanted)
            if before is None:
                raise InvalidArgument(f'No journal entry has entry_id {wanted!r}.')
            vocabulary = set(await service.list_tags())

            after = await service.update_tags(wanted, adding, removing)
            if after is None:
                raise InvalidArgument(f'No journal entry has entry_id {wanted!r}.')

            old, new = before.get('tags') or [], after.get('tags') or []
            added = [tag for tag in new if tag not in old]
            return TagUpdate(
                entry_id=wanted,
                tags=new,
                added=added,
                removed=[tag for tag in old if tag not in new],
                new_tags=[tag for tag in added if tag not in vocabulary],
            )

        return await runner.run('update_tags', operation, write=True)
