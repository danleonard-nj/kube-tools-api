"""Journal HTTP routes.

Endpoints
---------
POST   /api/journal/entries                              — create journal entry
GET    /api/journal/entries                              — list recent entries
GET    /api/journal/entries/<entry_id>                   — get full entry
POST   /api/journal/entries/<entry_id>/process           — request/retry processing
POST   /api/journal/entries/<entry_id>/title             — refresh auto-title
PATCH  /api/journal/entries/<entry_id>                   — update title/transcript
DELETE /api/journal/entries/<entry_id>                   — delete entry
POST   /api/journal/entries/<entry_id>/polish            — LLM-polish transcript
POST   /api/journal/entries/<entry_id>/polish/undo       — undo last polish
"""
from __future__ import annotations

from quart import request

from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from services.journal_insights_service import JournalInsightsService
from services.journal_processing_service import JournalProcessingService
from services.journal_service import JournalService, JournalServiceError

logger = get_logger(__name__)

journal_bp = MetaBlueprint('journal_bp', __name__)


@journal_bp.configure('/api/journal/entries', methods=['POST'], auth_scheme='default')
async def create_journal_entry(container):
    service: JournalService = container.resolve(JournalService)

    body = await request.get_json()
    if not body:
        return {'error': 'Request body is required'}, 400
    if not body.get('raw_transcript'):
        return {'error': 'raw_transcript is required'}, 400

    result = await service.create_entry(body)
    return result, 201


@journal_bp.configure('/api/journal/entries', methods=['GET'], auth_scheme='default')
async def list_journal_entries(container):
    service: JournalService = container.resolve(JournalService)

    limit = min(int(request.args.get('limit', 50)), 200)
    result = await service.list_entries(limit=limit)
    return result


@journal_bp.configure('/api/journal/entries/<entry_id>', methods=['GET'], auth_scheme='default')
async def get_journal_entry(container, entry_id: str):
    service: JournalService = container.resolve(JournalService)

    entry = await service.get_entry(entry_id)
    if not entry:
        return {'error': 'Entry not found'}, 404
    return entry


@journal_bp.configure('/api/journal/entries/<entry_id>/process', methods=['POST'], auth_scheme='default')
async def process_journal_entry(container, entry_id: str):
    """Event bus callback — executes LLM analysis for the given entry.
    Also serves as the manual re-trigger endpoint; process_entry() is idempotent.
    """
    processing_service: JournalProcessingService = container.resolve(JournalProcessingService)
    await processing_service.process_entry(entry_id)
    return {'entry_id': entry_id, 'accepted': True}, 202


@journal_bp.configure('/api/journal/entries/<entry_id>/title', methods=['POST'], auth_scheme='default')
async def refresh_journal_entry_title(container, entry_id: str):
    """Regenerate the auto-title for an entry (no-op when a manual title is set)."""
    service: JournalService = container.resolve(JournalService)

    entry = await service.refresh_title(entry_id)
    if not entry:
        return {'error': 'Entry not found or no transcript available'}, 404
    return entry


@journal_bp.configure('/api/journal/entries/<entry_id>', methods=['PATCH'], auth_scheme='default')
async def patch_journal_entry(container, entry_id: str):
    service: JournalService = container.resolve(JournalService)

    body = await request.get_json()
    if not body:
        return {'error': 'Request body is required'}, 400

    entry = await service.update_entry(entry_id, body)
    if not entry:
        return {'error': 'Entry not found'}, 404
    return entry


@journal_bp.configure('/api/journal/entries/<entry_id>', methods=['DELETE'], auth_scheme='default')
async def delete_journal_entry(container, entry_id: str):
    service: JournalService = container.resolve(JournalService)

    deleted = await service.delete_entry(entry_id)
    if not deleted:
        return {'error': 'Entry not found'}, 404
    return {'deleted': True}, 200


@journal_bp.configure('/api/journal/insights', methods=['GET'], auth_scheme='default')
async def get_journal_insights(container):
    service: JournalInsightsService = container.resolve(JournalInsightsService)

    days = min(int(request.args.get('days', 14)), 90)
    result = await service.get_insights(days=days)
    return result


_VALID_POLISH_MODES = {'grammar', 'organize', 'concise', 'expand', 'tone'}


@journal_bp.configure('/api/journal/entries/<entry_id>/polish', methods=['POST'], auth_scheme='default')
async def polish_journal_entry(container, entry_id: str):
    """Apply LLM polish to a transcript.

    Body: ``{"modes": ["grammar", "organize", "concise", "expand", "tone"]}``
    At least one valid mode is required.
    """
    service: JournalService = container.resolve(JournalService)

    body = await request.get_json() or {}
    modes = body.get('modes', [])

    if not isinstance(modes, list) or not modes:
        return {'error': 'modes must be a non-empty list'}, 400

    invalid = [m for m in modes if m not in _VALID_POLISH_MODES]
    if invalid:
        return {
            'error': f'Invalid modes: {invalid}',
            'valid_modes': sorted(_VALID_POLISH_MODES),
        }, 400

    entry = await service.polish_transcript(entry_id, modes)
    if not entry:
        return {'error': 'Entry not found or no transcript to polish'}, 404
    return entry


@journal_bp.configure('/api/journal/entries/<entry_id>/polish/undo', methods=['POST'], auth_scheme='default')
async def undo_journal_entry_polish(container, entry_id: str):
    """Restore the transcript to the state before the last polish."""
    service: JournalService = container.resolve(JournalService)

    entry = await service.undo_polish(entry_id)
    if not entry:
        return {'error': 'No polish to undo for this entry'}, 404
    return entry
