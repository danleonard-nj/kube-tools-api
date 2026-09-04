"""Journal service - CRUD and async processing dispatch."""
import uuid
from datetime import datetime
from typing import Any, List, Optional

from clients.gpt_client import GPTClient
from clients.identity_client import IdentityClient
from data.journal_attachment_repository import JournalAttachmentRepository
from data.journal_repository import JournalRepository
from domain.auth import AuthClient, ClientScope
from domain.events import JournalProcessEvent
from domain.gpt import GPTModel
from domain.journal import (
    JournalAttachment,
    JournalEntry,
    JournalEntryStatus,
    JournalProcessingMetadata,
    JournalSegment,
    JournalSource,
)
from framework.logger import get_logger
from framework.configuration import Configuration
from services.event_service import EventService
from framework.clients.feature_client import FeatureClientAsync


_TITLE_SYSTEM_PROMPT = (
    'You generate short, descriptive titles for journal entries. '
    'Return only the title — 3 to 7 words, no punctuation, no quotes.'
)

_POLISH_SYSTEM_PROMPT = (
    'You are a careful editing assistant for personal journal entries. '
    'Apply ONLY the requested adjustments listed below. '
    'Preserve the writer’s meaning, emotional truth, first-person voice, and specific details. '
    'You may rephrase, combine, split, reorder, or tighten sentences when it improves clarity, flow, or readability. '
    'Do not summarize, add new facts, soften important emotions, or make the writing sound generic. '
    'If meaningful improvements are possible, make them. '
    'Return only the polished text with no commentary, headers, or markdown.'
)

_POLISH_MODE_DESCRIPTIONS: dict = {
    'grammar': 'Fix grammar, spelling, punctuation, capitalization, and awkward transcription artifacts.',
    'organize': 'Improve paragraph structure and logical flow. Reorder nearby sentences when helpful, without changing meaning.',
    'concise': 'Tighten repetitive or wordy phrasing while preserving emphasis, emotion, and important details.',
    'expand': 'Lightly clarify terse, fragmented, or implied thoughts without inventing new facts or changing meaning.',
    'tone': 'Smooth rough, fragmented, or overly tangled phrasing into natural prose while preserving the writer’s voice and emotional intensity.',
}

TITLE_GENERATION_MODEL_FEATURE_KEY='gpt-model-journal-title-generation'
POLISH_MODEL_FEATURE_KEY='gpt-model-journal-polish'

logger = get_logger(__name__)


class JournalServiceError(Exception):
    pass


class JournalService:
    def __init__(
        self,
        journal_repository: JournalRepository,
        journal_attachment_repository: JournalAttachmentRepository,
        event_service: EventService,
        identity_client: IdentityClient,
        configuration: Configuration,
        gpt_client: GPTClient,
        feature_client: FeatureClientAsync,
    ):
        self._repository = journal_repository
        self._attachment_repository = journal_attachment_repository
        self._event_service = event_service
        self._identity_client = identity_client
        self._gpt = gpt_client
        self._base_url = configuration.gateway.get('api_gateway_base_url')
        self._feature_client = feature_client

    async def _get_feature_value(self, feature_key: str, default: Any) -> Any:
        try:
            value = await self._feature_client.is_enabled(feature_key)
            return value if value is not None else default
        except Exception as exc:
            logger.warning(f'Failed to fetch feature flag {feature_key}: {exc}')
            return default

    async def _generate_title(self, raw_transcript: str) -> Optional[str]:
        value = await self._get_feature_value(TITLE_GENERATION_MODEL_FEATURE_KEY, GPTModel.GPT_5_4_NANO)
        try:
            result = await self._gpt.generate_response(
                prompt=f'Journal entry:\n\n{raw_transcript}',
                model=value,
                system_prompt=_TITLE_SYSTEM_PROMPT,
                use_cache=False,
                max_output_tokens=20,
            )
            return result.text.strip() or None
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

    async def list_entries(self, limit: int = 50, tags: Optional[List[str]] = None) -> List[dict]:
        docs = await self._repository.list_recent(limit=limit, tags=tags or None)
        return [JournalEntry.from_entity(doc).model_dump() for doc in docs]

    async def list_tags(self) -> List[str]:
        return await self._repository.list_distinct_tags()

    async def get_entry(self, entry_id: str) -> Optional[dict]:
        doc = await self._repository.get_entry(entry_id)
        if not doc:
            return None
        return JournalEntry.from_entity(doc).model_dump()

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
        attempt_count = doc['processing']['attempt_count'] + 1

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

    @staticmethod
    def _normalize_tags(tags: list) -> List[str]:
        seen: set = set()
        result = []
        for t in tags:
            clean = t.strip().lower()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    async def update_entry(self, entry_id: str, body: dict) -> Optional[dict]:
        allowed_fields = {'title', 'raw_transcript', 'cleaned_transcript', 'status', 'tags'}
        update = {k: v for k, v in body.items() if k in allowed_fields}

        if 'tags' in update:
            update['tags'] = self._normalize_tags(update['tags'])
        if not update:
            return await self.get_entry(entry_id)

        raw_transcript_changed = 'raw_transcript' in update
        cleaned_transcript_changed = 'cleaned_transcript' in update

        if raw_transcript_changed:
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
        elif cleaned_transcript_changed:
            update['pre_polish_transcript'] = None

        updated = await self._repository.update_entry(entry_id, update)
        if not updated:
            return None

        if raw_transcript_changed:
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
        import difflib
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

        model = await self._get_feature_value(POLISH_MODEL_FEATURE_KEY, GPTModel.GPT_5_5_MINI)

        result = await self._gpt.generate_response(
            prompt=source_text,
            model=model,
            system_prompt=system_prompt,
            use_cache=False,
        )
        polished = result.text.strip()

        diff = difflib.unified_diff(
            source_text.splitlines(),
            polished.splitlines()
        )

        logger.info(f'Polish diff for entry {entry_id} (modes: {modes}):')
        logger.info('\n'.join(diff))

        # hd = difflib.HtmlDiff()
        # html_content = hd.make_file(source_text.splitlines(), polished.splitlines(), fromdesc='Original', todesc='Polished')

        # with open("diff.html", "w") as f:
        #     f.write(html_content)

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

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def _attachment_url(self, entry_id: str, attachment_id: str) -> str:
        return f'/api/journal/entries/{entry_id}/attachments/{attachment_id}'

    def _attachment_to_response(self, doc: dict) -> dict:
        attachment = JournalAttachment.from_entity(doc)
        result = attachment.model_dump()
        result['download_url'] = self._attachment_url(attachment.entry_id, attachment.attachment_id)
        return result

    async def upload_attachment(
        self,
        entry_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> Optional[dict]:
        if not await self._repository.get_entry(entry_id):
            return None
        doc = await self._attachment_repository.store(
            entry_id=entry_id,
            filename=filename,
            content_type=content_type,
            data=data,
        )
        logger.info(f'Attachment uploaded for entry {entry_id}: {doc["attachment_id"]}')
        return self._attachment_to_response(doc)

    async def list_attachments(self, entry_id: str) -> Optional[List[dict]]:
        if not await self._repository.get_entry(entry_id):
            return None
        docs = await self._attachment_repository.list_meta(entry_id)
        return [self._attachment_to_response(doc) for doc in docs]

    async def download_attachment(
        self, entry_id: str, attachment_id: str
    ) -> Optional[dict]:
        doc = await self._attachment_repository.get_meta(attachment_id)
        if not doc or doc['entry_id'] != entry_id:
            return None
        data = await self._attachment_repository.fetch_data(doc['gridfs_id'])
        if data is None:
            return None
        return {
            'data': data,
            'filename': doc['filename'],
            'content_type': doc['content_type'],
        }

    async def delete_attachment(self, entry_id: str, attachment_id: str) -> bool:
        doc = await self._attachment_repository.get_meta(attachment_id)
        if not doc or doc['entry_id'] != entry_id:
            return False
        deleted = await self._attachment_repository.delete(attachment_id)
        if deleted:
            logger.info(f'Attachment deleted for entry {entry_id}: {attachment_id}')
        return deleted
