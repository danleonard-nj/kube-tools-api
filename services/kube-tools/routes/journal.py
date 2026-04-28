"""Journal HTTP routes.

Endpoints
---------
POST   /api/journal/entries                        — create journal entry
GET    /api/journal/entries                        — list recent entries
GET    /api/journal/entries/<entry_id>             — get full entry
POST   /api/journal/entries/<entry_id>/process     — request/retry processing
PATCH  /api/journal/entries/<entry_id>             — update title/transcript
DELETE /api/journal/entries/<entry_id>             — delete entry
"""
from __future__ import annotations

from quart import request

from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
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
    service: JournalService = container.resolve(JournalService)

    body = await request.get_json(silent=True) or {}
    force = bool(body.get('force', False))

    try:
        result = await service.request_processing(entry_id, force=force)
        status_code = 202 if result.get('accepted') else 200
        return result, status_code
    except JournalServiceError as exc:
        return {'error': str(exc)}, 404


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
