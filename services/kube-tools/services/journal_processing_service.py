"""Journal processing service — two-stage LLM analysis of journal entries.

Stage 1: Summarization (_SUMMARY_SYSTEM_PROMPT)
Stage 2: Structured metadata extraction (_EXTRACTION_SYSTEM_PROMPT)

Both stages run concurrently against the raw transcript.
"""
import asyncio
import json
from datetime import datetime
from typing import Any, Dict

from clients.gpt_client import GPTClient
from data.journal_repository import JournalRepository
from domain.gpt import GPTModel
from domain.journal import JournalEntryStatus
from framework.clients.feature_client import FeatureClientAsync
from framework.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Stage 1 — summary
# ---------------------------------------------------------------------------
_SUMMARY_SYSTEM_PROMPT = """\
You are a personal journal summarization assistant.
Analyze the journal entry below and return strict JSON only — no markdown, no commentary.

Rules:
- Do not invent facts, diagnoses, emotions, motives, relationships, or events not present in the text.
- Preserve uncertainty; use wording like "may", "possibly", or "the writer was unsure" when the entry is uncertain.
- Preserve important concrete details: people, places, times, events, problems, decisions, plans, \
unresolved issues, and emotional context.
- Do not categorize, tag, or extract lists in this step.
- summary_short must be one factual sentence, max 24 words.
- summary_detailed must be 4 to 8 sentences and useful for future weekly/monthly summaries \
without rereading the full transcript.
- Prefer factual phrasing over interpretation.
- The transcript may contain filler words, false starts, or transcription artifacts — ignore these \
and focus on substantive content.

Return JSON in exactly this shape:
{
  "summary_short": "One factual sentence suitable for compact UI display.",
  "summary_detailed": "Four to eight sentence factual summary preserving key events, context, emotional tone, and unresolved issues."
}
"""

# ---------------------------------------------------------------------------
# Stage 2 — structured extraction
# ---------------------------------------------------------------------------
_EXTRACTION_SYSTEM_PROMPT = """\
You are a personal journal structured extraction assistant.
Extract structured metadata from the provided journal transcript.
Return strict JSON only — no markdown, no commentary.

Rules:
- Do not invent facts, diagnoses, emotions, motives, relationships, or events not present in the text.
- Preserve uncertainty.
- Prefer concrete, factual extraction over interpretation.
- Keep extracted list items short and specific.
- Do not turn every reflection, wish, insecurity, hope, fear, or general concern into an action item or open loop.
- Extract symptoms, action items, and risk flags ONLY when clearly supported by the text.
- For risk_flags, detect language that may indicate crisis or medical concern; do not generate alarmist conclusions.
- The transcript may contain filler words, false starts, or transcription artifacts — ignore these \
and focus on substantive content.

Field rules:
- key_events: max 8. Concrete events/facts only.
- people_mentioned: max 8. Named people or explicit roles only. Do not include vague descriptions or broad groups.
- places_or_contexts: max 6. Short labels only.
- stressors: max 5. Short labels or brief phrases, not full sentences.
- positive_developments: max 5. Concrete wins, encouragement, progress, or stabilizing factors.
- open_loops: max 5. Only pending tasks, unresolved decisions, or follow-ups. \
Do not include general hopes, fears, identity concerns, or emotional reflections.
- themes: max 5. Lowercase human-readable phrases, not snake_case.
- symptoms: max 5. Only physical or mental symptoms explicitly mentioned.
- action_items: max 5. Only concrete actions the writer plans, needs, or may need to take.
- mood.score: integer 1-10, where 1 is very negative, 5 is neutral, and 10 is very positive.
- mood.label: concise label such as "negative", "slightly negative", "neutral", "hopeful", "positive", or "mixed".
- mood.confidence: number from 0 to 1.

Return JSON in exactly this shape:
{
  "key_events": ["Concrete event, detail, or situation mentioned in the entry."],
  "people_mentioned": ["Named person or explicit role mentioned."],
  "places_or_contexts": ["Short place, app, work context, health context, shop, home, etc."],
  "stressors": ["Short specific stressor."],
  "positive_developments": ["Concrete win, hopeful note, useful conversation, progress, or stabilizing factor."],
  "open_loops": ["Clearly pending task, unresolved decision, or follow-up."],
  "themes": ["human-readable theme"],
  "mood": {"score": 5, "label": "neutral", "confidence": 0.80},
  "symptoms": ["symptom explicitly mentioned"],
  "action_items": ["concrete action explicitly mentioned"],
  "risk_flags": {"crisis_language": false, "medical_concern": false}
}
"""

# Max lengths per extraction field (mirrors prompt rules)
_LIST_LIMITS: Dict[str, int] = {
    'key_events': 8,
    'people_mentioned': 8,
    'places_or_contexts': 6,
    'stressors': 5,
    'positive_developments': 5,
    'open_loops': 5,
    'themes': 5,
    'symptoms': 5,
    'action_items': 5,
}

ANALYSIS_MODEL_FEATURE_KEY = 'gpt-model-journal-analysis'


class JournalProcessingService:
    def __init__(
        self,
        journal_repository: JournalRepository,
        gpt_client: GPTClient,
        feature_client: FeatureClientAsync
    ):
        self._repository = journal_repository
        self._gpt = gpt_client
        self._feature_client = feature_client

    async def get_feature_value(self, key: str, default: Any = None) -> Any:
        try:
            return await self._feature_client.is_enabled(key)
        except Exception as exc:
            logger.error(f'Error fetching feature flag {key}: {exc}', exc_info=True)
            return default

    # ------------------------------------------------------------------
    # public entry point
    # ------------------------------------------------------------------

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

            # Resolve model once and share across both calls
            model = await self.get_feature_value(
                ANALYSIS_MODEL_FEATURE_KEY, GPTModel.GPT_5_5,
            )

            # Run both stages concurrently — neither depends on the other
            summary_result, extraction_result = await asyncio.gather(
                self._summarize(raw_transcript, model),
                self._extract_structure(raw_transcript, model),
            )

            analysis = {**summary_result, **extraction_result}

            await self._repository.update_entry(entry_id, {
                'status': JournalEntryStatus.PROCESSED,
                'analysis': analysis,
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

    # ------------------------------------------------------------------
    # Stage 1 — summarize
    # ------------------------------------------------------------------

    async def _summarize(self, raw_transcript: str, model: str) -> dict:
        """Return dict with summary_short, summary_detailed, summary_usage."""

        prompt = f'Journal entry:\n\n{raw_transcript}'

        try:
            result = await self._call_json_llm(
                system_prompt=_SUMMARY_SYSTEM_PROMPT,
                user_payload=prompt,
                model=model,
            )
        except Exception as exc:
            logger.warning(
                f'Summary LLM call failed, using fallback: {exc}',
                exc_info=True,
            )
            return {
                'summary_short': '',
                'summary_detailed': '',
                'summary_usage': {},
            }

        result.setdefault('summary_short', '')
        result.setdefault('summary_detailed', '')
        result['summary_usage'] = result.pop('usage', {})
        return result

    # ------------------------------------------------------------------
    # Stage 2 — structured extraction
    # ------------------------------------------------------------------

    async def _extract_structure(self, raw_transcript: str, model: str) -> dict:
        """Return dict with key_events, people_mentioned, mood, etc."""

        user_payload = f'Journal transcript:\n\n{raw_transcript}'

        try:
            result = await self._call_json_llm(
                system_prompt=_EXTRACTION_SYSTEM_PROMPT,
                user_payload=user_payload,
                model=model,
            )
        except Exception as exc:
            logger.warning(
                f'Extraction LLM call failed, using defaults: {exc}',
                exc_info=True,
            )
            result = {}

        result = self._normalize_extraction(result)
        result['extraction_usage'] = result.pop('usage', {})
        return result

    # ------------------------------------------------------------------
    # shared LLM helper
    # ------------------------------------------------------------------

    async def _call_json_llm(
        self,
        system_prompt: str,
        user_payload: str,
        model: str,
    ) -> dict:
        """Call the LLM and parse the response as JSON."""

        response = await self._gpt.generate_response(
            prompt=user_payload,
            system_prompt=system_prompt,
            model=model,
            use_cache=False,
        )

        content = response.text.strip()

        # Strip markdown code fences the model sometimes adds
        if content.startswith('```'):
            lines = content.splitlines()
            content = '\n'.join(
                line for line in lines
                if not line.strip().startswith('```')
            )

        parsed = json.loads(content)
        parsed['usage'] = response.data.get('usage', {})
        return parsed

    # ------------------------------------------------------------------
    # validation / normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_extraction(data: dict) -> dict:
        """Ensure all extraction keys exist and values are within bounds."""

        # Lists — default to empty, truncate to max
        for key, limit in _LIST_LIMITS.items():
            val = data.get(key)
            if not isinstance(val, list):
                data[key] = []
            else:
                data[key] = val[:limit]

        # Mood
        mood = data.get('mood')
        if not isinstance(mood, dict):
            mood = {'score': 5, 'label': 'neutral', 'confidence': 0.5}
        mood['score'] = max(1, min(10, int(mood.get('score', 5))))
        mood['label'] = str(mood.get('label', 'neutral'))
        mood['confidence'] = max(0.0, min(1.0, float(mood.get('confidence', 0.5))))
        data['mood'] = mood

        # Risk flags
        rf = data.get('risk_flags')
        if not isinstance(rf, dict):
            rf = {}
        rf['crisis_language'] = bool(rf.get('crisis_language', False))
        rf['medical_concern'] = bool(rf.get('medical_concern', False))
        data['risk_flags'] = rf

        return data