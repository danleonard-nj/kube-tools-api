"""Stats: counts and trends over a date range."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from mcp_server.models import JournalStats, LabelCount, MoodDay, OpenItem, ThemeCount
from mcp_server.tools.common import EndDate, Principal, StartDate, ToolRunner, resolve_range, utc_bounds
from services.journal_insights_service import JournalInsightsService

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

DEFAULT_DAYS = 30
MAX_OPEN_ITEMS = 50


def register(server: MCPServer, runner: ToolRunner) -> None:
    name = runner.config.tool_name
    zone = runner.config.zone
    time_zone = runner.config.time_zone

    @server.tool(
        name=name('stats'),
        title='Journal stats',
        description=(
            'Counts and trends over a date range (default: the last 30 days): how many '
            'entries and on how many days, streaks, average and daily mood, the most frequent '
            'themes, people and stressors, and the action items and open loops raised, each '
            'with the entry it came from. Use it for "how have I been" or "what keeps coming '
            'up" questions, then read individual entries for detail.'
        ),
        annotations=READ_ONLY,
    )
    async def stats(start_date: StartDate = None, end_date: EndDate = None) -> JournalStats:
        async def operation(_: Principal) -> JournalStats:
            start, end = resolve_range(start_date, end_date, zone, default_days=DEFAULT_DAYS)
            start_utc, end_utc = utc_bounds(start, end, zone)
            result = await runner.resolve(JournalInsightsService).get_stats(start_utc, end_utc, zone)

            open_items = result['open_items']
            return JournalStats(
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                time_zone=time_zone,
                entry_count=result['entry_count'],
                truncated=result['truncated'],
                entries_awaiting_analysis=result['entries_awaiting_analysis'],
                days_with_entries=result['days_with_entries'],
                longest_streak_days=result['longest_streak_days'],
                streak_at_end_days=result['streak_at_end_days'],
                mood_average=result['mood_average'],
                mood_daily=[MoodDay(**day) for day in result['mood_daily']],
                themes=[ThemeCount(**theme) for theme in result['themes']],
                people=[LabelCount(**person) for person in result['people']],
                stressors=[LabelCount(**stressor) for stressor in result['stressors']],
                open_items=[OpenItem(**item) for item in open_items[:MAX_OPEN_ITEMS]],
                open_items_total=len(open_items),
            )

        return await runner.run('stats', operation)
