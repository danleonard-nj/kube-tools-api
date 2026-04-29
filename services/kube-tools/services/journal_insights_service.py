"""Journal insights service — rollup analytics over recent processed entries."""
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from clients.gpt_client import GPTClient
from data.journal_repository import JournalRepository
from domain.gpt import GPTModel
from domain.journal import JournalEntryStatus
from framework.logger import get_logger

logger = get_logger(__name__)

_INSIGHTS_SYSTEM_PROMPT = """\
You are a thoughtful personal journal analyst performing a windowed retrospective.
You are given a structured digest of journal entries from a specific recent period.
Each entry includes its date, summary, key points, emotional tone, themes, \
symptoms noted, and open action items.

Your task is to synthesise all of this into a rich, human-readable insight report.

Rules:
- Do not invent facts not present in the provided entries.
- Identify patterns, recurring themes, and meaningful shifts across the window.
- Highlight any unresolved action items or repeated concerns.
- Describe the mood arc as a narrative, not just labels.
- Return strict JSON only — no markdown, no code fences, no commentary.

Return JSON in exactly this shape:
{
  "narrative": "Two to four sentence holistic summary of the period.",
  "mood_arc": "One to two sentence description of how mood evolved across the window.",
  "dominant_themes": ["theme_a", "theme_b"],
  "key_facts": ["Notable fact or event extracted from entries"],
  "open_action_items": ["Unresolved action item"],
  "patterns_of_concern": ["Any recurring symptom, worry, or risk indicator — omit if none"],
  "positive_highlights": ["Wins, moments of clarity, or positive developments — omit if none"]
}
"""


class JournalInsightsService:
    def __init__(
        self,
        journal_repository: JournalRepository,
        gpt_client: GPTClient,
    ):
        self._repository = journal_repository
        self._gpt = gpt_client

    async def get_insights(self, days: int = 14) -> dict:
        since = datetime.utcnow() - timedelta(days=days)
        docs = await self._repository.list_entries_since(since=since, limit=500)

        processed = [
            d for d in docs
            if d.get('status') == JournalEntryStatus.PROCESSED and d.get('analysis')
        ]

        llm_summary = await self._build_llm_summary(processed, days)

        return {
            'generated_at': datetime.utcnow().isoformat(),
            'window_days': days,
            'summary': self._build_summary(processed),
            'llm_summary': llm_summary,
            'mood_trend': self._build_mood_trend(processed, days),
            'streak': self._build_streak(docs),
            'themes': self._build_themes(processed),
            'recent_moods': self._build_recent_moods(processed),
        }

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_summary(self, processed: List[dict]) -> dict:
        bullets: List[str] = []
        source_entry_ids: List[str] = []
        for doc in processed:
            entry_bullets = (doc.get('analysis') or {}).get('bullets') or []
            if entry_bullets:
                bullets.extend(entry_bullets)
                source_entry_ids.append(doc.get('entry_id'))
        return {
            'bullets': bullets[:10],
            'source_entry_ids': source_entry_ids,
        }

    # ------------------------------------------------------------------
    # LLM windowed summary
    # ------------------------------------------------------------------

    def _extract_facts(self, doc: dict) -> dict:
        """Distil a single processed entry into the structured digest sent to the LLM."""
        analysis = doc.get('analysis') or {}
        mood = analysis.get('mood') or {}
        return {
            'date': self._date_str(doc.get('created_at')),
            'title': doc.get('title'),
            'summary': analysis.get('summary'),
            'bullets': analysis.get('bullets') or [],
            'themes': analysis.get('themes') or [],
            'mood': {
                'score': mood.get('score'),
                'label': mood.get('label'),
            },
            'symptoms': analysis.get('symptoms') or [],
            'action_items': analysis.get('action_items') or [],
            'risk_flags': analysis.get('risk_flags') or {},
        }

    async def _build_llm_summary(self, processed: List[dict], days: int) -> dict:
        """Use an LLM to produce a rich windowed narrative over the processed entries."""
        if not processed:
            return {'error': 'no_processed_entries'}

        # Sort oldest → newest so the model can follow chronological flow
        sorted_entries = sorted(
            processed,
            key=lambda d: self._parse_dt(d.get('created_at')) or datetime.min,
        )

        facts = [self._extract_facts(d) for d in sorted_entries]

        prompt = (
            f'The following is a structured digest of {len(facts)} journal '
            f'entries from the last {days} days, ordered oldest to newest.\n\n'
            + json.dumps(facts, indent=2, default=str)
        )

        try:
            result = await self._gpt.generate_completion(
                prompt=prompt,
                system_prompt=_INSIGHTS_SYSTEM_PROMPT,
                model=GPTModel.GPT_5,
                use_cache=False,
                temperature=0.4,
            )

            content = result.content.strip()

            # Strip any accidental markdown fences
            if content.startswith('```'):
                lines = content.splitlines()
                content = '\n'.join(
                    line for line in lines
                    if not line.strip().startswith('```')
                )

            parsed = json.loads(content)
            parsed['entry_count'] = len(facts)
            return parsed

        except Exception as exc:
            logger.error(f'LLM windowed summary failed: {exc}', exc_info=True)
            return {'error': str(exc)}

    def _build_mood_trend(self, processed: List[dict], days: int) -> dict:
        daily: Dict[str, list] = defaultdict(list)
        for doc in processed:
            date_str = self._date_str(doc.get('created_at'))
            if not date_str:
                continue
            mood = (doc.get('analysis') or {}).get('mood') or {}
            score = mood.get('score')
            if score is not None:
                daily[date_str].append({'score': score, 'label': mood.get('label')})

        today = datetime.utcnow().date()
        points = []
        for i in range(days - 1, -1, -1):
            d = today - timedelta(days=i)
            key = d.strftime('%Y-%m-%d')
            day_data = daily.get(key, [])
            if day_data:
                avg_score = round(sum(x['score'] for x in day_data) / len(day_data))
                label = day_data[-1]['label']
            else:
                avg_score = None
                label = None
            points.append({'date': key, 'score': avg_score, 'label': label})

        return {'points': points}

    def _build_streak(self, docs: List[dict]) -> dict:
        entry_dates: set = set()
        last_entry_at: Optional[datetime] = None

        for doc in docs:
            created_at = self._parse_dt(doc.get('created_at'))
            if not created_at:
                continue
            entry_dates.add(created_at.date())
            if last_entry_at is None or created_at > last_entry_at:
                last_entry_at = created_at

        today = datetime.utcnow().date()

        # Current streak: consecutive days ending today (or yesterday if no entry today)
        current_days = 0
        check = today
        while check in entry_dates:
            current_days += 1
            check -= timedelta(days=1)
        if current_days == 0:
            check = today - timedelta(days=1)
            while check in entry_dates:
                current_days += 1
                check -= timedelta(days=1)

        # Longest streak within the fetched window
        longest_days = 0
        run = 0
        prev = None
        for d in sorted(entry_dates):
            if prev and (d - prev).days == 1:
                run += 1
            else:
                run = 1
            if run > longest_days:
                longest_days = run
            prev = d

        return {
            'current_days': current_days,
            'longest_days': longest_days,
            'last_entry_at': last_entry_at.isoformat() if last_entry_at else None,
        }

    def _build_themes(self, processed: List[dict], limit: int = 12) -> dict:
        counter: Counter = Counter()
        last_seen: Dict[str, str] = {}

        for doc in processed:
            themes = (doc.get('analysis') or {}).get('themes') or []
            date_str = self._date_str(doc.get('created_at'))
            for theme in themes:
                counter[theme] += 1
                if date_str:
                    if theme not in last_seen or date_str > last_seen[theme]:
                        last_seen[theme] = date_str

        return {
            'themes': [
                {'label': label, 'count': count, 'last_seen': last_seen.get(label)}
                for label, count in counter.most_common(limit)
            ]
        }

    def _build_recent_moods(self, processed: List[dict], limit: int = 5) -> dict:
        moods = []
        for doc in processed:
            mood = (doc.get('analysis') or {}).get('mood') or {}
            score = mood.get('score')
            label = mood.get('label')
            if score is None and label is None:
                continue
            moods.append({
                'date': self._date_str(doc.get('created_at')),
                'label': label,
                'score': score,
                'entry_id': doc.get('entry_id'),
            })
            if len(moods) >= limit:
                break
        return {'moods': moods}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_dt(value) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @classmethod
    def _date_str(cls, value) -> Optional[str]:
        dt = cls._parse_dt(value)
        return dt.strftime('%Y-%m-%d') if dt else None
