"""Journal processing service — LLM analysis of journal entries."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from clients.gpt_client import GPTClient
from data.journal_repository import JournalRepository
from domain.gpt import GPTModel
from domain.journal import JournalEntryStatus
from framework.logger import get_logger

logger = get_logger(__name__)

_ANALYSIS_SYSTEM_PROMPT = """\
You are a personal journal analysis assistant. \
Analyze the journal entry below and return strict JSON only — no markdown, no commentary.

Rules:
- Do not invent facts, diagnoses, or events not present in the text.
- Preserve uncertainty; do not speculate beyond what is stated.
- cleaned_transcript should be faithful to the original wording, removing \
obvious filler words, repeated phrases, and transcription artifacts only.
- Extract themes, mood, symptoms, action items, and risk flags ONLY when \
clearly supported by the text. Leave lists empty when nothing applies.
- For risk_flags, detect language that may indicate crisis or medical concern; \
do not generate alarmist conclusions.

Return JSON in exactly this shape (all keys required):
{
  "cleaned_transcript": "...",
  "summary": "One or two sentence summary.",
  "bullets": ["Key point 1", "Key point 2"],
  "themes": ["theme_a", "theme_b"],
  "mood": {"score": 5, "label": "neutral", "confidence": 0.80},
  "symptoms": ["symptom if mentioned"],
  "action_items": ["action if mentioned"],
  "risk_flags": {"crisis_language": false, "medical_concern": false}
}
"""


class JournalProcessingService:
    def __init__(
        self,
        journal_repository: JournalRepository,
        gpt_client: GPTClient,
    ):
        self._repository = journal_repository
        self._gpt = gpt_client

    async def process_entry(self, entry_id: str) -> None:
        logger.info(f'Journal processing started: {entry_id}')

        doc = await self._repository.get_entry(entry_id)
        if not doc:
            logger.error(f'Journal entry not found for processing: {entry_id}')
            return

        # Idempotency guard — do not re-enter if already running
        if doc.get('status') == JournalEntryStatus.PROCESSING:
            logger.info(f'Entry {entry_id} already processing, skipping')
            return

        await self._repository.update_entry(entry_id, {
            'status': JournalEntryStatus.PROCESSING,
            'processing.started_at': datetime.utcnow(),
        })

        try:
            raw_transcript = doc.get('raw_transcript', '').strip()
            if not raw_transcript:
                raise ValueError('raw_transcript is empty — nothing to process')

            result = await self._run_analysis(raw_transcript)

            cleaned_transcript = result.pop('cleaned_transcript', None)

            await self._repository.update_entry(entry_id, {
                'status': JournalEntryStatus.PROCESSED,
                'cleaned_transcript': cleaned_transcript,
                'analysis': result,
                'processing.completed_at': datetime.utcnow(),
                'processing.error': None,
            })

            logger.info(f'Journal entry processed successfully: {entry_id}')

        except Exception as exc:
            logger.error(f'Journal processing failed for {entry_id}: {exc}', exc_info=True)
            await self._repository.update_entry(entry_id, {
                'status': JournalEntryStatus.FAILED,
                'processing.failed_at': datetime.utcnow(),
                'processing.error': str(exc),
            })

    async def _run_analysis(self, raw_transcript: str) -> dict:
        prompt = f'Journal entry:\n\n{raw_transcript}'

        completion = await self._gpt.generate_completion(
            prompt=prompt,
            system_prompt=_ANALYSIS_SYSTEM_PROMPT,
            model=GPTModel.GPT_4O_MINI,
            use_cache=False,
            temperature=0.3,
        )

        content = completion.content.strip()

        # Strip markdown code fences the model sometimes adds despite instructions
        if content.startswith('```'):
            lines = content.splitlines()
            content = '\n'.join(
                line for line in lines
                if not line.strip().startswith('```')
            )

        return json.loads(content)
