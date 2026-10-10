"""Journal documents -> result models, field by field.

Kept apart from the tools so the mapping is in one place: this is where the
allowlist in ``mcp_server.models`` is applied to stored documents.
"""

from __future__ import annotations

import re
from datetime import tzinfo
from typing import Any, List, Optional

from mcp_server.models import Analysis, Attachment, Entry, EntrySummary, Mood
from mcp_server.tools.common import to_local

SNIPPET_RADIUS = 90


def _mood(value: Any) -> Optional[Mood]:
    if not isinstance(value, dict) or (value.get('score') is None and not value.get('label')):
        return None
    score = value.get('score')
    return Mood(score=score if isinstance(score, int) else None, label=value.get('label'))


def _transcript(doc: dict) -> tuple[str, bool]:
    cleaned = (doc.get('cleaned_transcript') or '').strip()
    if cleaned:
        return cleaned, True
    return (doc.get('raw_transcript') or '').strip(), False


def _word_count(text: str) -> int:
    return len(text.split())


def snippet(doc: dict, text: str) -> Optional[str]:
    """Text around the first case-insensitive match, whitespace collapsed."""
    analysis = doc.get('analysis') or {}
    pattern = re.compile(re.escape(text), re.IGNORECASE)
    for source in (doc.get('cleaned_transcript'), doc.get('raw_transcript'),
                   analysis.get('summary_detailed'), analysis.get('summary_short'), doc.get('title')):
        if not source:
            continue
        match = pattern.search(source)
        if match is None:
            continue
        start = max(0, match.start() - SNIPPET_RADIUS)
        end = min(len(source), match.end() + SNIPPET_RADIUS)
        excerpt = ' '.join(source[start:end].split())
        return f"{'…' if start else ''}{excerpt}{'…' if end < len(source) else ''}"
    return None


def entry_summary(doc: dict, zone: tzinfo, search_text: Optional[str] = None) -> EntrySummary:
    recorded = to_local(doc.get('created_at'), zone)
    analysis = doc.get('analysis') or {}
    transcript, _ = _transcript(doc)
    return EntrySummary(
        entry_id=doc['entry_id'],
        date=recorded.date().isoformat() if recorded else None,
        recorded_at=recorded.isoformat(timespec='minutes') if recorded else None,
        title=doc.get('title'),
        tags=doc.get('tags'),
        source=doc.get('source'),
        status=doc.get('status'),
        mood=_mood(analysis.get('mood')),
        summary=analysis.get('summary_short') or None,
        word_count=_word_count(transcript),
        snippet=snippet(doc, search_text) if search_text else None,
    )


def full_entry(doc: dict, attachments: List[dict], zone: tzinfo, time_zone: str) -> Entry:
    recorded = to_local(doc.get('created_at'), zone)
    analysis = doc.get('analysis')
    transcript, cleaned = _transcript(doc)
    return Entry(
        entry_id=doc['entry_id'],
        date=recorded.date().isoformat() if recorded else None,
        recorded_at=recorded.isoformat(timespec='minutes') if recorded else None,
        title=doc.get('title'),
        title_is_manual=bool(doc.get('is_manual_title')),
        tags=doc.get('tags'),
        source=doc.get('source'),
        status=doc.get('status'),
        transcript=transcript,
        transcript_is_cleaned=cleaned,
        word_count=_word_count(transcript),
        analysis=Analysis(
            summary_short=analysis.get('summary_short'),
            summary_detailed=analysis.get('summary_detailed'),
            key_events=analysis.get('key_events'),
            people_mentioned=analysis.get('people_mentioned'),
            places_or_contexts=analysis.get('places_or_contexts'),
            stressors=analysis.get('stressors'),
            positive_developments=analysis.get('positive_developments'),
            open_loops=analysis.get('open_loops'),
            themes=analysis.get('themes'),
            mood=_mood(analysis.get('mood')),
            symptoms=analysis.get('symptoms'),
            action_items=analysis.get('action_items'),
        ) if isinstance(analysis, dict) and analysis else None,
        attachments=[
            Attachment(
                filename=item.get('filename') or 'attachment',
                content_type=item.get('content_type'),
                size_bytes=item.get('size_bytes'),
            )
            for item in attachments
        ],
        time_zone=time_zone,
    )
