"""Journal service - CRUD and async processing dispatch."""
import uuid
from datetime import datetime
from typing import List, Optional

from clients.gpt_client import GPTClient
from clients.identity_client import IdentityClient
from data.journal_repository import JournalRepository
from domain.auth import AuthClient, ClientScope
from domain.events import JournalProcessEvent
from domain.gpt import GPTModel
from domain.journal import (
    JournalEntry,
    JournalEntryStatus,
    JournalProcessingMetadata,
    JournalSegment,
    JournalSource,
)
from framework.logger import get_logger
from framework.configuration import Configuration
from services.event_service import EventService

_TITLE_SYSTEM_PROMPT = (
    'You generate short, descriptive titles for journal entries. '
    'Return only the title — 3 to 7 words, no punctuation, no quotes.'
)

_POLISH_SYSTEM_PROMPT = (
    'You are a light editing assistant for personal journal entries. '
    'Apply ONLY the requested adjustments listed below — do not paraphrase, '
    'summarize, add content, or change the writer\'s voice or meaning. '
    'Return only the polished text with no commentary, headers, or markdown.'
)

_POLISH_MODE_DESCRIPTIONS: dict = {
    'grammar': 'Fix grammar, spelling, and punctuation errors.',
    'organize': 'Restructure sentences and paragraphs for logical flow without changing content.',
    'concise': 'Remove redundant phrases and excessive filler words.',
    'expand': 'Lightly elaborate terse or incomplete sentences to improve clarity.',
    'tone': 'Smooth rough or fragmented phrasing into natural prose while preserving meaning.',
}

logger = get_logger(__name__)


class JournalServiceError(Exception):
    pass


class JournalService:
    def __init__(
        self,
        journal_repository: JournalRepository,
        event_service: EventService,
        identity_client: IdentityClient,
        configuration: Configuration,
        gpt_client: GPTClient,
    ):
        self._repository = journal_repository
        self._event_service = event_service
        self._identity_client = identity_client
        self._gpt = gpt_client
        self._base_url = configuration.gateway.get('api_gateway_base_url')

    async def _generate_title(self, raw_transcript: str) -> Optional[str]:
        try:
            result = await self._gpt.generate_completion(
                prompt=f'Journal entry:\n\n{raw_transcript[:1500]}',
                model=GPTModel.GPT_4_1_NANO,
                system_prompt=_TITLE_SYSTEM_PROMPT,
                temperature=0.3,
                use_cache=False,
                max_tokens=20,
            )
            return result.content.strip() or None
        except Exception as exc:
            logger.warning(f'Auto-title generation failed: {exc}')
            return None

    async def _dispatch_processing(self, entry_id: str) -> None:
        token = await self._identity_client.get_token(
            AuthClient.KubeToolsApi, ClientScope.KubeToolsApi
        )
        event = JournalProcessEvent(
            entry_id=entry_id,
            base_url=self._base_url,
            token=token,
        )
        await self._event_service.dispatch_event(event)

    async def create_entry(self, body: dict) -> dict:
        entry_id = str(uuid.uuid4())
        now = datetime.utcnow()

        segments = [
            JournalSegment.model_validate(s)
            for s in (body.get('segments') or [])
        ]

        processing_meta = JournalProcessingMetadata(
            requested_at=now,
            attempt_count=0,
        )

        manual_title = body.get('title')

        entry = JournalEntry(
            entry_id=entry_id,
            created_at=now,
            updated_at=now,
            title=manual_title,
            is_manual_title=bool(manual_title),
            source=body.get('source', JournalSource.VOICE),
            status=JournalEntryStatus.QUEUED,
            segments=segments,
            raw_transcript=body.get('raw_transcript', ''),
            cleaned_transcript=None,
            analysis=None,
            processing=processing_meta,
        )

        await self._repository.insert_entry(entry.model_dump())

        # Generate title synchronously on commit when no manual title was supplied
        if not entry.title:
            generated_title = await self._generate_title(entry.raw_transcript)
            if generated_title:
                await self._repository.update_entry(entry_id, {'title': generated_title})
                entry = entry.model_copy(update={'title': generated_title})

        logger.info(f'Journal entry created: {entry_id}')

        await self._dispatch_processing(entry_id)

        return entry.model_dump()

    async def list_entries(self, limit: int = 50) -> List[dict]:
        docs = await self._repository.list_recent(limit=limit)
        entries = []
        for doc in docs:
            entry = JournalEntry.from_entity(doc)
            if entry:
                entries.append(entry.model_dump())
        return entries

    async def get_entry(self, entry_id: str) -> Optional[dict]:
        doc = await self._repository.get_entry(entry_id)
        if not doc:
            return None
        entry = JournalEntry.from_entity(doc)
        return entry.model_dump() if entry else None

    async def request_processing(self, entry_id: str, force: bool = False) -> dict:
        """Re-queue an existing entry for processing via the event bus.

        Returns a status dict indicating whether the request was accepted.
        Callers should not use this to trigger the actual LLM work directly -
        that happens when the Service Bus consumer calls back to /process.
        """
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

        await self._dispatch_processing(entry_id)
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

        transcript_changed = 'raw_transcript' in update

        if transcript_changed:
            now = datetime.utcnow()
            update.update({
                'cleaned_transcript': None,
                'pre_polish_transcript': None,
                'analysis': None,
                'status': JournalEntryStatus.QUEUED,
                'processing.requested_at': now,
                'processing.error': None,
                'processing.failed_at': None,
            })

        updated = await self._repository.update_entry(entry_id, update)
        if not updated:
            return None

        if transcript_changed:
            await self._dispatch_processing(entry_id)
            logger.info(f'Re-queued analysis for updated transcript: {entry_id}')

        return await self.get_entry(entry_id)

    async def delete_entry(self, entry_id: str) -> bool:
        return await self._repository.delete_entry(entry_id)

    async def polish_transcript(self, entry_id: str, modes: list) -> Optional[dict]:
        """Apply lightweight LLM edits to cleaned_transcript (or raw_transcript).

        The previous value is saved to ``pre_polish_transcript`` so callers can
        undo with :meth:`undo_polish`.
        """
        doc = await self._repository.get_entry(entry_id)
        if not doc:
            return None

        source_text = (doc.get('cleaned_transcript') or doc.get('raw_transcript', '')).strip()
        if not source_text:
            return None

        mode_lines = [
            f'- {_POLISH_MODE_DESCRIPTIONS[m]}'
            for m in modes
            if m in _POLISH_MODE_DESCRIPTIONS
        ]
        if not mode_lines:
            return await self.get_entry(entry_id)

        system_prompt = (
            _POLISH_SYSTEM_PROMPT
            + '\n\nRequested adjustments:\n'
            + '\n'.join(mode_lines)
        )

        result = await self._gpt.generate_completion(
            prompt=source_text,
            model=GPTModel.GPT_4O,
            system_prompt=system_prompt,
            temperature=0.3,
            use_cache=False,
        )
        polished = result.content.strip()

        await self._repository.update_entry(entry_id, {
            'pre_polish_transcript': source_text,
            'cleaned_transcript': polished,
        })

        logger.info(f'Transcript polished for entry: {entry_id} (modes: {modes})')
        return await self.get_entry(entry_id)

    async def undo_polish(self, entry_id: str) -> Optional[dict]:
        """Restore cleaned_transcript from pre_polish_transcript."""
        doc = await self._repository.get_entry(entry_id)
        if not doc:
            return None

        pre_polish = doc.get('pre_polish_transcript')
        if not pre_polish:
            return None

        await self._repository.update_entry(entry_id, {
            'cleaned_transcript': pre_polish,
            'pre_polish_transcript': None,
        })

        logger.info(f'Polish undone for entry: {entry_id}')
        return await self.get_entry(entry_id)

    async def refresh_title(self, entry_id: str) -> Optional[dict]:
        """Regenerate the auto-title for an entry.

        Returns the updated entry, or None if the entry does not exist or has
        no transcript.  When a manual title is already set it is left untouched
        and the existing entry is returned unchanged.
        """
        doc = await self._repository.get_entry(entry_id)
        if not doc:
            return None

        # Manual title always wins — don't overwrite it
        if doc.get('is_manual_title'):
            entry = JournalEntry.from_entity(doc)
            return entry.model_dump() if entry else None

        raw_transcript = doc.get('raw_transcript', '').strip()
        if not raw_transcript:
            return None

        generated_title = await self._generate_title(raw_transcript)
        if generated_title:
            await self._repository.update_entry(entry_id, {'title': generated_title})

        return await self.get_entry(entry_id)
