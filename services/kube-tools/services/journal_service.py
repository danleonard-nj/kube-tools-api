"""Journal service — CRUD and async processing dispatch."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from data.journal_repository import JournalRepository
from domain.journal import (
    JournalEntry,
    JournalEntryStatus,
    JournalProcessingMetadata,
    JournalSegment,
    JournalSource,
)
from framework.logger import get_logger
from utilities.utils import fire_task

if TYPE_CHECKING:
    from services.journal_processing_service import JournalProcessingService

logger = get_logger(__name__)


class JournalServiceError(Exception):
    pass


class JournalService:
    def __init__(
        self,
        journal_repository: JournalRepository,
        journal_processing_service: 'JournalProcessingService',
    ):
        self._repository = journal_repository
        self._processing_service = journal_processing_service

    async def create_entry(self, body: dict) -> dict:
        entry_id = str(uuid.uuid4())
        now = datetime.utcnow()

        segments = [
            JournalSegment.from_entity(s)
            for s in (body.get('segments') or [])
        ]

        processing_meta = JournalProcessingMetadata(
            requested_at=now,
            attempt_count=0,
        )

        entry = JournalEntry(
            entry_id=entry_id,
            created_at=now,
            updated_at=now,
            title=body.get('title'),
            source=body.get('source', JournalSource.VOICE),
            status=JournalEntryStatus.QUEUED,
            segments=segments,
            raw_transcript=body.get('raw_transcript', ''),
            cleaned_transcript=None,
            analysis=None,
            processing=processing_meta,
        )

        await self._repository.insert_entry(entry.to_dict())
        logger.info(f'Journal entry created: {entry_id}')

        fire_task(self._processing_service.process_entry(entry_id))

        return entry.to_dict()

    async def list_entries(self, limit: int = 50) -> List[dict]:
        docs = await self._repository.list_recent(limit=limit)
        entries = []
        for doc in docs:
            entry = JournalEntry.from_entity(doc)
            if entry:
                entries.append(entry.to_dict())
        return entries

    async def get_entry(self, entry_id: str) -> Optional[dict]:
        doc = await self._repository.get_entry(entry_id)
        if not doc:
            return None
        entry = JournalEntry.from_entity(doc)
        return entry.to_dict() if entry else None

    async def request_processing(self, entry_id: str, force: bool = False) -> dict:
        doc = await self._repository.get_entry(entry_id)
        if not doc:
            raise JournalServiceError(f'Journal entry not found: {entry_id}')

        status = doc.get('status')

        if status == JournalEntryStatus.PROCESSING:
            return {
                'entry_id': entry_id,
                'status': status,
                'accepted': True,
                'message': 'Already processing',
            }

        if status == JournalEntryStatus.PROCESSED and not force:
            return {
                'entry_id': entry_id,
                'status': status,
                'accepted': False,
                'message': 'Already processed. Pass force=true to reprocess.',
            }

        now = datetime.utcnow()
        processing_data = doc.get('processing') or {}
        attempt_count = (processing_data.get('attempt_count') or 0) + 1

        await self._repository.update_entry(entry_id, {
            'status': JournalEntryStatus.QUEUED,
            'processing.requested_at': now,
            'processing.attempt_count': attempt_count,
            'processing.error': None,
            'processing.failed_at': None,
        })

        fire_task(self._processing_service.process_entry(entry_id))
        logger.info(f'Journal processing queued for entry: {entry_id} (attempt {attempt_count})')

        return {
            'entry_id': entry_id,
            'status': JournalEntryStatus.QUEUED,
            'accepted': True,
            'message': 'Processing queued',
        }

    async def update_entry(self, entry_id: str, body: dict) -> Optional[dict]:
        allowed_fields = {'title', 'raw_transcript', 'status'}
        update = {k: v for k, v in body.items() if k in allowed_fields}
        if not update:
            return await self.get_entry(entry_id)
        updated = await self._repository.update_entry(entry_id, update)
        if not updated:
            return None
        return await self.get_entry(entry_id)

    async def delete_entry(self, entry_id: str) -> bool:
        return await self._repository.delete_entry(entry_id)
