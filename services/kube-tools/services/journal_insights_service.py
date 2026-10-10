"""Journal insights service — rollup analytics over recent processed entries."""
import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Dict, List, Optional

from clients.gpt_client import GPTClient
from data.journal_repository import JournalRepository
from domain.gpt import GPTModel
from domain.journal import JournalEntryStatus
from framework.logger import get_logger

logger = get_logger(__name__)

_INSIGHTS_SYSTEM_PROMPT = """\
You are a thoughtful personal journal analyst performing a windowed retrospective.
You are given a structured digest of journal entries (or pre-summarised chunk digests) \
from a specific recent period.
Each entry or digest may include: date, title, short and detailed summaries, a brief \
transcript excerpt in the writer's own words, key events, people mentioned, places and \
contexts, stressors, positive developments, open loops, emotional tone, themes, \
symptoms noted, and open action items.

Your task is to synthesise all of this into a rich, human-readable insight report.

Rules:
- Do not invent facts not present in the provided entries.
- Use transcript excerpts as ground-truth voice when they add detail beyond the summaries.
- Identify patterns, recurring themes, and meaningful shifts across the window.
- Note recurring people, places, or contexts where relevant.
- Highlight any unresolved action items or repeated concerns.
- Describe the mood arc as a narrative, not just labels.
- Return strict JSON only — no markdown, no code fences, no commentary.

Return JSON in exactly this shape:
{
  "narrative": "Two to four sentence holistic summary of the period.",
  "mood_arc": "One to two sentence description of how mood evolved across the window.",
  "dominant_themes": ["theme_a", "theme_b"],
  "key_facts": ["Notable fact or event extracted from entries"],
  "people_and_contexts": ["Recurring person, place, or situation worth noting"],
  "open_action_items": ["Unresolved action item"],
  "patterns_of_concern": ["Any recurring symptom, worry, or risk indicator — omit if none"],
  "positive_highlights": ["Wins, moments of clarity, or positive developments — omit if none"]
}
"""

_CHUNK_SYSTEM_PROMPT = """\
You are a personal journal analyst condensing a small batch of journal entries into a \
compact intermediate digest for a larger rollup analysis.
Each entry may include: date, title, short and detailed summaries, a brief transcript \
excerpt, key events, people mentioned, places/contexts, stressors, positive developments, \
open loops, themes, mood, symptoms, and action items.

Return strict JSON only — no markdown, no code fences, no commentary.

Return JSON in exactly this shape:
{
  "date_range": "YYYY-MM-DD to YYYY-MM-DD",
  "entry_count": 0,
  "narrative": "Two to three sentence factual summary of this sub-period.",
  "key_events": ["Notable event"],
  "people_mentioned": ["Person name"],
  "places_or_contexts": ["Place or context"],
  "stressors": ["Stressor"],
  "positive_developments": ["Positive development"],
  "open_loops": ["Unresolved item"],
  "themes": ["theme"],
  "mood_summary": "One sentence describing overall mood of this sub-period.",
  "action_items": ["action item"],
  "symptoms": ["symptom noted"]
}
"""

_CHUNK_THRESHOLD = 20   # entries above which map-reduce chunking is used
_CHUNK_SIZE = 15        # entries per chunk in the map phase
_TRANSCRIPT_EXCERPT_LEN = 400  # max chars of cleaned_transcript included per entry


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

    async def get_stats(
        self,
        start: datetime,
        end: datetime,
        zone: tzinfo,
        max_entries: int = 2000,
    ) -> dict:
        """Counts and trends over a date range, without any LLM call.

        `start` (inclusive) and `end` (exclusive) are naive UTC, like the stored
        `created_at`; days are reported in `zone`. Unlike `get_insights`, the
        window is arbitrary rather than counted back from today.
        """
        docs, total = await self._repository.search_entries(start=start, end=end, limit=max_entries)

        def local_day(doc: dict) -> Optional[date]:
            created_at = self._parse_dt(doc.get('created_at'))
            if created_at is None:
                return None
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            return created_at.astimezone(zone).date()

        days = {doc.get('entry_id'): local_day(doc) for doc in docs}
        entry_days = {day for day in days.values() if day}
        processed = [doc for doc in docs if doc.get('analysis')]

        moods_by_day: Dict[date, List[int]] = defaultdict(list)
        themes: Counter = Counter()
        people: Counter = Counter()
        stressors: Counter = Counter()
        theme_last_seen: Dict[str, date] = {}
        open_items: List[dict] = []

        for doc in processed:  # newest first
            analysis = doc['analysis']
            day = days.get(doc.get('entry_id'))
            score = (analysis.get('mood') or {}).get('score')
            if isinstance(score, (int, float)) and day:
                moods_by_day[day].append(score)
            for theme in analysis.get('themes') or []:
                themes[theme] += 1
                if day and (theme not in theme_last_seen or day > theme_last_seen[theme]):
                    theme_last_seen[theme] = day
            people.update(analysis.get('people_mentioned') or [])
            stressors.update(analysis.get('stressors') or [])
            for kind, field in (('action_item', 'action_items'), ('open_loop', 'open_loops')):
                for text in analysis.get(field) or []:
                    if text:
                        open_items.append({
                            'kind': kind,
                            'text': text,
                            'date': day.isoformat() if day else None,
                            'entry_id': doc.get('entry_id'),
                        })

        scores = [score for day_scores in moods_by_day.values() for score in day_scores]
        last_day = (end.replace(tzinfo=timezone.utc).astimezone(zone) - timedelta(microseconds=1)).date()

        return {
            'entry_count': len(docs),
            'truncated': total > len(docs),
            'entries_awaiting_analysis': len(docs) - len(processed),
            'days_with_entries': len(entry_days),
            'longest_streak_days': self._longest_run(entry_days),
            'streak_at_end_days': self._run_ending(entry_days, last_day),
            'mood_average': round(sum(scores) / len(scores), 1) if scores else None,
            'mood_daily': [
                {'date': day.isoformat(), 'score': round(sum(values) / len(values), 1), 'entries': len(values)}
                for day, values in sorted(moods_by_day.items())
            ],
            'themes': [
                {'label': label, 'count': count, 'last_seen': theme_last_seen[label].isoformat() if label in theme_last_seen else None}
                for label, count in themes.most_common(12)
            ],
            'people': [{'label': label, 'count': count} for label, count in people.most_common(12)],
            'stressors': [{'label': label, 'count': count} for label, count in stressors.most_common(10)],
            'open_items': open_items,
        }

    @staticmethod
    def _longest_run(days: set) -> int:
        longest = run = 0
        previous = None
        for day in sorted(days):
            run = run + 1 if previous and (day - previous).days == 1 else 1
            longest = max(longest, run)
            previous = day
        return longest

    @staticmethod
    def _run_ending(days: set, last_day: date) -> int:
        """Consecutive days with entries ending on `last_day`, or the day before."""
        check = last_day if last_day in days else last_day - timedelta(days=1)
        run = 0
        while check in days:
            run += 1
            check -= timedelta(days=1)
        return run

    # ------------------------------------------------------------------
    # Internal builders
    # ------------------------------------------------------------------

    def _build_summary(self, processed: List[dict]) -> dict:
        key_events: List[str] = []
        source_entry_ids: List[str] = []
        for doc in processed:
            entry_events = (doc.get('analysis') or {}).get('key_events') or []
            if entry_events:
                key_events.extend(entry_events)
                source_entry_ids.append(doc.get('entry_id'))
        return {
            'key_events': key_events[:10],
            'source_entry_ids': source_entry_ids,
        }

    # ------------------------------------------------------------------
    # LLM windowed summary
    # ------------------------------------------------------------------

    def _extract_facts(self, doc: dict) -> dict:
        """Distil a single processed entry into the structured digest sent to the LLM."""
        analysis = doc.get('analysis') or {}
        mood = analysis.get('mood') or {}
        cleaned = doc.get('cleaned_transcript') or ''
        excerpt = cleaned[:_TRANSCRIPT_EXCERPT_LEN].rstrip() if cleaned else None
        return {
            'date': self._date_str(doc.get('created_at')),
            'title': doc.get('title'),
            'summary_short': analysis.get('summary_short'),
            'summary_detailed': analysis.get('summary_detailed'),
            'transcript_excerpt': excerpt,
            'key_events': analysis.get('key_events') or [],
            'people_mentioned': analysis.get('people_mentioned') or [],
            'places_or_contexts': analysis.get('places_or_contexts') or [],
            'stressors': analysis.get('stressors') or [],
            'positive_developments': analysis.get('positive_developments') or [],
            'open_loops': analysis.get('open_loops') or [],
            'themes': analysis.get('themes') or [],
            'mood': {
                'score': mood.get('score'),
                'label': mood.get('label'),
            },
            'symptoms': analysis.get('symptoms') or [],
            'action_items': analysis.get('action_items') or [],
            'risk_flags': analysis.get('risk_flags') or {},
        }

    @staticmethod
    def _render_entry_as_text(fact: dict) -> str:
        """Render a single extracted-facts dict as a compact structured-text block."""
        lines: List[str] = []

        # Header
        date = fact.get('date') or 'unknown date'
        title = fact.get('title')
        mood = fact.get('mood') or {}
        mood_label = mood.get('label') or ''
        mood_score = mood.get('score')
        mood_str = f'{mood_label} ({mood_score}/10)' if mood_score is not None else mood_label
        header = f'[{date}]'
        if title:
            header += f'  "{title}"'
        if mood_str:
            header += f'  |  Mood: {mood_str}'
        lines.append(header)

        # Summaries
        if fact.get('summary_short'):
            lines.append(fact['summary_short'])
        if fact.get('summary_detailed'):
            lines.append(fact['summary_detailed'])

        # Verbatim excerpt
        if fact.get('transcript_excerpt'):
            lines.append(f'> {fact["transcript_excerpt"]}')

        # Structured fields — only emit non-empty lists
        def _inline(items: list) -> str:
            return ' · '.join(str(x) for x in items if x)

        if fact.get('key_events'):
            lines.append(f'Key events: {_inline(fact["key_events"])}')
        if fact.get('people_mentioned'):
            lines.append(f'People: {_inline(fact["people_mentioned"])}')
        if fact.get('places_or_contexts'):
            lines.append(f'Places/contexts: {_inline(fact["places_or_contexts"])}')
        if fact.get('stressors'):
            lines.append(f'Stressors: {_inline(fact["stressors"])}')
        if fact.get('positive_developments'):
            lines.append(f'Positives: {_inline(fact["positive_developments"])}')
        if fact.get('open_loops'):
            lines.append(f'Open loops: {_inline(fact["open_loops"])}')
        if fact.get('action_items'):
            lines.append(f'Action items: {_inline(fact["action_items"])}')
        if fact.get('symptoms'):
            lines.append(f'Symptoms: {_inline(fact["symptoms"])}')
        if fact.get('themes'):
            lines.append(f'Themes: {_inline(fact["themes"])}')

        return '\n'.join(lines)

    @classmethod
    def _render_facts_as_text(cls, facts: List[dict]) -> str:
        """Render a list of extracted-facts dicts as a separator-delimited text block."""
        separator = '---'
        blocks = [separator]
        for fact in facts:
            blocks.append(cls._render_entry_as_text(fact))
            blocks.append(separator)
        return '\n'.join(blocks)

    @staticmethod
    def _render_chunk_digest_as_text(digest: dict) -> str:
        """Render an intermediate chunk digest (JSON dict) as structured text."""
        lines: List[str] = []
        date_range = digest.get('date_range') or 'unknown range'
        count = digest.get('entry_count', '?')
        lines.append(f'[{date_range}]  ({count} entries)')
        if digest.get('narrative'):
            lines.append(digest['narrative'])
        if digest.get('mood_summary'):
            lines.append(f'Mood: {digest["mood_summary"]}')

        def _inline(items) -> str:
            return ' · '.join(str(x) for x in (items or []) if x)

        for label, key in [
            ('Key events', 'key_events'),
            ('People', 'people_mentioned'),
            ('Places/contexts', 'places_or_contexts'),
            ('Stressors', 'stressors'),
            ('Positives', 'positive_developments'),
            ('Open loops', 'open_loops'),
            ('Action items', 'action_items'),
            ('Symptoms', 'symptoms'),
            ('Themes', 'themes'),
        ]:
            if digest.get(key):
                lines.append(f'{label}: {_inline(digest[key])}')
        return '\n'.join(lines)

    async def _summarize_chunk(self, chunk_facts: List[dict]) -> dict:
        """Map phase: condense one chronological chunk into an intermediate digest."""
        prompt = (
            f'The following is a structured batch of {len(chunk_facts)} journal entries.\n\n'
            + self._render_facts_as_text(chunk_facts)
        )
        try:
            result = await self._gpt.generate_response(
                prompt=prompt,
                system_prompt=_CHUNK_SYSTEM_PROMPT,
                model=GPTModel.GPT_5_5,
                use_cache=False,
            )
            content = result.text.strip()
            if content.startswith('```'):
                lines = content.splitlines()
                content = '\n'.join(
                    line for line in lines
                    if not line.strip().startswith('```')
                )
            return json.loads(content)
        except Exception as exc:
            logger.warning(f'Chunk summarization failed: {exc}')
            return {'error': str(exc), 'entry_count': len(chunk_facts)}

    async def _build_llm_summary(self, processed: List[dict], days: int) -> dict:
        """Use an LLM to produce a rich windowed narrative over the processed entries.

        For windows with more than _CHUNK_THRESHOLD entries a map-reduce strategy is
        used: entries are split into chronological chunks, each chunk is condensed into
        an intermediate digest, and those digests are fed to the final synthesis call.
        """
        if not processed:
            return {'error': 'no_processed_entries'}

        # Sort oldest → newest so the model can follow chronological flow
        sorted_entries = sorted(
            processed,
            key=lambda d: self._parse_dt(d.get('created_at')) or datetime.min,
        )

        facts = [self._extract_facts(d) for d in sorted_entries]

        # --- map phase (only when there are many entries) ---
        if len(facts) > _CHUNK_THRESHOLD:
            chunks = [facts[i:i + _CHUNK_SIZE] for i in range(0, len(facts), _CHUNK_SIZE)]
            logger.info(
                f'LLM summary: chunking {len(facts)} entries into {len(chunks)} chunks'
            )
            digest: list = []
            for chunk in chunks:
                digest.append(await self._summarize_chunk(chunk))
            digest_blocks = '\n---\n'.join(
                self._render_chunk_digest_as_text(d) for d in digest
            )
            prompt = (
                f'The following are {len(digest)} intermediate digests covering the last '
                f'{days} days ({len(facts)} total entries), ordered oldest to newest.\n\n'
                f'---\n{digest_blocks}\n---'
            )
        else:
            prompt = (
                f'The following is a structured digest of {len(facts)} journal '
                f'entries from the last {days} days, ordered oldest to newest.\n\n'
                + self._render_facts_as_text(facts)
            )

        try:
            result = await self._gpt.generate_response(
                prompt=prompt,
                system_prompt=_INSIGHTS_SYSTEM_PROMPT,
                model=GPTModel.GPT_5_5,
                use_cache=False,
            )

            content = result.text.strip()

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
