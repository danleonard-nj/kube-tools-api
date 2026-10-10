"""What every tool module shares: the caller and the runner.

Ported from plaid-sync's ``mcp_server/tools/common.py``. Every tool is thin:
validate arguments, call an existing journal service, return a model from
``mcp_server.models``. ``ToolRunner.run`` owns timing, logging, the write-scope
check and turning failures into ``ToolError`` messages a model can act on, so
no individual tool repeats it.

Error text reaching a client is limited to ``InvalidArgument`` (our own checks
on the model's arguments) and ``ToolError``. Every other failure becomes a
generic message with a reference, so journal text on a document a service
rejected cannot travel out through an error either.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as day_start, timedelta, timezone, tzinfo
from typing import Annotated, Any, Awaitable, Callable, List, Optional, Tuple, TypeVar

from framework.logger import get_logger
from framework.mcp.auth import API_KEY_CLIENT_ID
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from models.mcp_config import McpConfig

logger = get_logger(__name__)

T = TypeVar('T')

MAX_PAGE_SIZE = 100
MAX_RANGE_DAYS = 3660

StartDate = Annotated[
    Optional[str],
    Field(default=None, description="Inclusive start date, YYYY-MM-DD, in the journal's time zone."),
]
EndDate = Annotated[
    Optional[str],
    Field(default=None, description="Inclusive end date, YYYY-MM-DD, in the journal's time zone. Defaults to today."),
]
EntryId = Annotated[str, Field(description='The entry_id of a journal entry, as returned by the search tool.')]


class InvalidArgument(ValueError):
    """A tool argument the model can fix; its message is returned to the client."""


@dataclass(frozen=True)
class Principal:
    """Who is calling: the user the token was approved by, and through which client."""

    subject: str
    client_id: str
    can_write: bool


class ToolRunner:
    """Runs tool bodies against the journal services.

    MCP tools are called by the SDK, not Quart, so they resolve services from
    the DI container at call time rather than through a route's ``container``.
    """

    def __init__(self, config: McpConfig):
        self.config = config

    def resolve(self, service_type: type[T]) -> T:
        from utilities.provider import ContainerProvider
        return ContainerProvider.get_service_provider().resolve(service_type)

    def principal(self) -> Principal:
        token = get_access_token()
        if token is None:
            # BearerAuth guards the endpoint, so a tool never runs without one.
            raise ToolError('Not authenticated.')

        if token.client_id == API_KEY_CLIENT_ID:
            # The static key is the owner's own credential (Claude Code by
            # header), so it has full access.
            return Principal(subject='', client_id=API_KEY_CLIENT_ID, can_write=True)

        return Principal(
            subject=token.subject or '',
            client_id=token.client_id,
            can_write=self.config.write_scope in token.scopes)

    async def run(self, tool: str, operation: Callable[[Principal], Awaitable[T]], *, write: bool = False) -> T:
        """Execute one tool body with timing, logging and error translation."""
        principal = self.principal()
        call_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()

        if write and not principal.can_write:
            logger.info('MCP tool refused: tool=%s client=%s reason=read-only', tool, principal.client_id)
            raise ToolError(
                'This connection is read-only. To make changes, the user has to reconnect '
                'this app and tick "Also allow changes" on the approval page.')

        status = 'ok'
        try:
            return await operation(principal)
        except ToolError:
            status = 'refused'
            raise
        except InvalidArgument as exc:
            # Written for the caller, and built only from the caller's own input.
            status = 'invalid'
            raise ToolError(str(exc)) from exc
        except Exception as exc:
            status = 'error'
            logger.exception('MCP tool failed: tool=%s call=%s', tool, call_id)
            raise ToolError(
                f'The request could not be completed just now (reference {call_id}). '
                'Try again shortly; do not treat this as an empty result.') from exc
        finally:
            # Counts and timings only: arguments and results are journal text.
            logger.info(
                'MCP tool: tool=%s client=%s status=%s duration_ms=%.1f call=%s',
                tool, principal.client_id, status,
                (time.perf_counter() - started) * 1000, call_id)


# -- Arguments ------------------------------------------------------------------


def parse_date(value: Optional[str], name: str) -> Optional[date]:
    if value is None or not str(value).strip():
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise InvalidArgument(f'{name} must be a date in YYYY-MM-DD form, got {value!r}.') from None


def resolve_range(
    start_date: Optional[str],
    end_date: Optional[str],
    zone: tzinfo,
    *,
    default_days: Optional[int],
) -> Tuple[Optional[date], Optional[date]]:
    """Validated local (start, end), both inclusive.

    With `default_days`, a missing start is that many days back from the end
    and a missing end is today. Without it, a range given by neither date is
    unbounded, and one given by a start alone runs to today.
    """
    today = datetime.now(zone).date()
    start = parse_date(start_date, 'start_date')
    end = parse_date(end_date, 'end_date')
    if default_days is not None:
        end = end or today
        start = start or end - timedelta(days=default_days - 1)
    elif start is not None and end is None:
        end = today
    if start is not None and end is not None:
        if start > end:
            raise InvalidArgument('start_date is after end_date; swap them.')
        if (end - start).days > MAX_RANGE_DAYS:
            raise InvalidArgument(f'Date ranges are limited to {MAX_RANGE_DAYS} days; narrow the range.')
    return start, end


def utc_bounds(
    start: Optional[date],
    end: Optional[date],
    zone: tzinfo,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Local inclusive days -> naive UTC [start, end), as `created_at` is stored."""
    def midnight(day: date) -> datetime:
        return datetime.combine(day, day_start(), zone).astimezone(timezone.utc).replace(tzinfo=None)

    return (
        midnight(start) if start else None,
        midnight(end + timedelta(days=1)) if end else None,
    )


def to_local(value: Any, zone: tzinfo) -> Optional[datetime]:
    """A stored timestamp (naive UTC) in the journal's zone."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone)


def clamp_limit(limit: int, maximum: int = MAX_PAGE_SIZE) -> int:
    if limit < 1:
        raise InvalidArgument('limit must be at least 1.')
    return min(limit, maximum)


def check_offset(offset: int) -> int:
    if offset < 0:
        raise InvalidArgument('offset must not be negative.')
    return offset


def as_list(value: Any) -> List[str]:
    """Tool list arguments, normalised: None or empty means none."""
    if not value:
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def require_entry_id(value: str) -> str:
    value = (value or '').strip()
    if not value:
        raise InvalidArgument('entry_id is required.')
    return value
