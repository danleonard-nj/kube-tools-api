"""Journal MCP tools: output shape, filters, time zone, write scope and errors.

Tools are called over MCP (the real blueprint, authenticated with the API key or
a read-only OAuth token) against the real JournalService and
JournalInsightsService, backed by an in-memory repository that mirrors the Mongo
query semantics. The Mongo filter itself is checked separately at the end.
"""

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from pydantic import BaseModel
from quart import Quart

import mcp_server.models as models
from data.journal_repository import JournalRepository
from mcp_server.app import create_mcp_blueprint
from models.mcp_config import McpConfig
from services.journal_insights_service import JournalInsightsService
from services.journal_service import JournalService
from services.mcp_auth_service import McpAuthService
from tests.mcp_fakes import FakeOAuthRepository, FakeProvider
from utilities.provider import ContainerProvider

API_KEY = 'k' * 40
READ_ONLY_TOKEN = 'read-only-token'
CONFIG = McpConfig(enabled=True, api_key=API_KEY, oauth={'owner_password': 'p' * 40})

# Leaked into a result, any of these would mean a field escaped the allowlist.
SECRETS = ('SECRET-ERROR', 'PRE-POLISH', 'clip-xyz', 'gridfs-123', 'crisis_language',
           'risk_flags', 'prompt_tokens', 'download_url', 'processing')


def entry(entry_id, created_at, **fields):
    doc = {
        'entry_id': entry_id,
        'created_at': created_at,
        'updated_at': created_at,
        'title': f'Title {entry_id}',
        'is_manual_title': False,
        'source': 'voice',
        'status': 'processed',
        'tags': [],
        'segments': [{'clip_id': 'clip-xyz', 'transcript': 'segment'}],
        'raw_transcript': '',
        'cleaned_transcript': None,
        'pre_polish_transcript': 'PRE-POLISH',
        'analysis': None,
        'processing': {'attempt_count': 1, 'error': 'SECRET-ERROR'},
    }
    doc.update(fields)
    return doc


def analysis(**fields):
    base = {
        'summary_short': None, 'summary_detailed': None, 'key_events': [], 'people_mentioned': [],
        'places_or_contexts': [], 'stressors': [], 'positive_developments': [], 'open_loops': [],
        'themes': [], 'mood': None, 'symptoms': [], 'action_items': [],
        'risk_flags': {'crisis_language': True, 'medical_concern': False},
        'summary_usage': {'prompt_tokens': 1234},
    }
    base.update(fields)
    return base


def seed():
    return [
        # 02:30 UTC on 30 Sep is 22:30 on 29 Sep in New York.
        entry('e1', datetime(2026, 9, 30, 2, 30), tags=['work'],
              raw_transcript='raw words', cleaned_transcript='Long day. I need to call the dentist tomorrow.',
              analysis=analysis(summary_short='A long work day', mood={'score': 6, 'label': 'tired'},
                                themes=['work', 'sleep'], people_mentioned=['Sam'], stressors=['deadline'],
                                action_items=['Call the dentist'], open_loops=['Decide on the trip'])),
        entry('e2', datetime(2026, 9, 30, 15, 0), tags=['work', 'family'],
              raw_transcript='Had lunch with Alex at the harbour.',
              analysis=analysis(summary_short='Lunch with Alex', mood={'score': 8, 'label': 'content'},
                                themes=['work'], people_mentioned=['Sam', 'Alex'])),
        entry('e3', datetime(2026, 10, 1, 13, 0), status='queued', source='text',
              raw_transcript='Quick note about the Dentist appointment'),
    ]


class FakeJournalRepository:
    """In-memory JournalRepository, matching the Mongo semantics the tools rely on."""

    FIELDS = ('title', 'cleaned_transcript', 'raw_transcript', 'analysis.summary_short', 'analysis.summary_detailed')

    def __init__(self, docs):
        self.docs = {doc['entry_id']: doc for doc in docs}

    @staticmethod
    def _field(doc, path):
        value = doc
        for part in path.split('.'):
            value = (value or {}).get(part) if isinstance(value, dict) else None
        return value

    async def insert_entry(self, document):
        self.docs[document['entry_id']] = dict(document)

    async def get_entry(self, entry_id):
        doc = self.docs.get(entry_id)
        return {**doc, '_id': 'oid'} if doc else None

    async def update_entry(self, entry_id, update):
        if entry_id not in self.docs:
            return False
        for key, value in update.items():
            if '.' in key:
                parent, child = key.split('.', 1)
                self.docs[entry_id].setdefault(parent, {})[child] = value
            else:
                self.docs[entry_id][key] = value
        return True

    async def search_entries(self, start=None, end=None, tags=None, text=None, limit=50, offset=0):
        found = []
        for doc in self.docs.values():
            if start and doc['created_at'] < start or end and doc['created_at'] >= end:
                continue
            if tags and not set(tags) <= set(doc.get('tags') or []):
                continue
            if text and not any(text.lower() in (self._field(doc, f) or '').lower() for f in self.FIELDS):
                continue
            found.append({k: v for k, v in doc.items() if k not in ('segments', 'pre_polish_transcript')})
        found.sort(key=lambda d: d['created_at'], reverse=True)
        return found[offset:offset + limit], len(found)

    async def list_distinct_tags(self):
        return sorted({tag for doc in self.docs.values() for tag in doc.get('tags') or []})

    async def count_tags(self):
        counts = {}
        for doc in self.docs.values():
            for tag in doc.get('tags') or []:
                counts[tag] = counts.get(tag, 0) + 1
        return [{'tag': t, 'entry_count': c} for t, c in sorted(counts.items(), key=lambda i: (-i[1], i[0]))]


@pytest.fixture
def repository():
    return FakeJournalRepository(seed())


@pytest.fixture
def journal(repository):
    configuration = MagicMock()
    configuration.gateway = {'api_gateway_base_url': 'https://api.dan-leonard.com'}
    gpt = AsyncMock()
    gpt.generate_response = AsyncMock(return_value=SimpleNamespace(text='Generated Title'))
    identity = AsyncMock()
    identity.get_token = AsyncMock(return_value='token')
    attachments = AsyncMock()
    attachments.list_meta = AsyncMock(return_value=[
        {'attachment_id': 'a1', 'entry_id': 'e1', 'filename': 'photo.jpg', 'content_type': 'image/jpeg',
         'size_bytes': 2048, 'created_at': datetime(2026, 9, 30), 'gridfs_id': 'gridfs-123'}])
    features = AsyncMock()
    features.is_enabled = AsyncMock(return_value=None)
    return JournalService(
        journal_repository=repository,
        journal_attachment_repository=attachments,
        event_service=AsyncMock(),
        identity_client=identity,
        configuration=configuration,
        gpt_client=gpt,
        feature_client=features,
    )


@pytest_asyncio.fixture
async def app(monkeypatch, repository, journal):
    """A test client on a served app: the MCP session manager starts once per test."""
    store = FakeOAuthRepository()
    store.access[READ_ONLY_TOKEN] = {
        'client_id': 'claude', 'scopes': [CONFIG.read_scope], 'resource': CONFIG.resource_url,
        'expires_at': 4102444800}
    provider = FakeProvider({
        McpConfig: CONFIG,
        McpAuthService: McpAuthService(store, CONFIG),
        JournalService: journal,
        JournalInsightsService: JournalInsightsService(journal_repository=repository, gpt_client=AsyncMock()),
    })
    monkeypatch.setattr(ContainerProvider, 'get_service_provider', lambda *args: provider)

    quart_app = Quart(__name__)
    quart_app.register_blueprint(create_mcp_blueprint(CONFIG))
    async with quart_app.test_app() as test_app:
        yield test_app.test_client()


async def rpc(client, method, params=None, token=API_KEY):
    response = await client.post('/api/tools/journal/mcp', headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json, text/event-stream',
        'MCP-Protocol-Version': '2025-11-25',
    }, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})
    assert response.status_code == 200
    body = await response.get_data(as_text=True)
    data = [line[len('data: '):] for line in body.splitlines() if line.startswith('data: ')]
    return json.loads(data[-1])['result']


async def call(app, tool, token=API_KEY, **arguments):
    """(structured result, None) on success, (None, error text) on a tool error."""
    result = await rpc(app, 'tools/call', {'name': f'journal_{tool}', 'arguments': arguments}, token)
    if result.get('isError'):
        return None, ' '.join(part.get('text', '') for part in result['content'])
    return result['structuredContent'], None


def assert_no_secrets(value):
    text = json.dumps(value)
    for secret in SECRETS:
        assert secret not in text, secret


# -- Surface ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_tool_is_listed(app):
    tools = {tool['name']: tool for tool in (await rpc(app, 'tools/list'))['tools']}
    assert set(tools) == {
        'journal_search_entries', 'journal_get_entry', 'journal_stats', 'journal_list_tags',
        'journal_create_entry', 'journal_set_title', 'journal_update_tags'}
    for name in ('journal_search_entries', 'journal_get_entry', 'journal_stats', 'journal_list_tags'):
        assert tools[name]['annotations']['readOnlyHint'] is True
    for name in ('journal_create_entry', 'journal_set_title', 'journal_update_tags'):
        assert tools[name]['annotations']['readOnlyHint'] is False
        assert tools[name]['annotations']['destructiveHint'] is False


def _fields(model, seen=None):
    seen = seen if seen is not None else set()
    if model in seen:
        return
    seen.add(model)
    for name, field in model.model_fields.items():
        yield name
        for arg in getattr(field.annotation, '__args__', ()) + (field.annotation,):
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                yield from _fields(arg, seen)


def test_result_models_declare_no_internal_fields():
    # The models are the allowlist. A field named like processing state, LLM
    # usage, storage ids or the risk classifier must be added deliberately --
    # and this test changed with it.
    forbidden = ('processing', 'error', 'usage', 'token', 'gridfs', 'risk', 'segment', 'clip',
                 'pre_polish', 'download', '_id')
    result_models = [m for m in vars(models).values()
                     if isinstance(m, type) and issubclass(m, BaseModel) and m.__module__ == models.__name__]
    for model in result_models:
        for name in _fields(model):
            assert not any(word in name for word in forbidden if name != 'entry_id'), f'{model.__name__}.{name}'


# -- Search -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_lists_newest_first_with_local_dates(app):
    result, error = await call(app, 'search_entries')
    assert error is None
    assert [e['entry_id'] for e in result['entries']] == ['e3', 'e2', 'e1']
    assert result['total'] == 3 and result['has_more'] is False
    assert result['time_zone'] == 'America/New_York'
    e1 = result['entries'][2]
    assert e1['date'] == '2026-09-29'
    assert e1['recorded_at'] == '2026-09-29T22:30-04:00'
    assert e1['mood'] == {'score': 6, 'label': 'tired'}
    assert e1['summary'] == 'A long work day'
    assert e1['word_count'] == 9
    assert_no_secrets(result)


@pytest.mark.asyncio
@pytest.mark.parametrize('day, expected', [
    ('2026-09-29', ['e1']),   # stored on 30 Sep UTC, written on the 29th locally
    ('2026-09-30', ['e2']),
    ('2026-10-01', ['e3']),
])
async def test_date_filters_use_the_journal_time_zone(app, day, expected):
    result, _ = await call(app, 'search_entries', start_date=day, end_date=day)
    assert [e['entry_id'] for e in result['entries']] == expected


@pytest.mark.asyncio
async def test_tag_filter_ignores_case_and_needs_every_tag(app):
    result, _ = await call(app, 'search_entries', tags=['WORK'])
    assert [e['entry_id'] for e in result['entries']] == ['e2', 'e1']
    result, _ = await call(app, 'search_entries', tags=['work', ' Family '])
    assert [e['entry_id'] for e in result['entries']] == ['e2']


@pytest.mark.asyncio
async def test_text_search_returns_a_snippet_around_the_match(app):
    result, _ = await call(app, 'search_entries', text='dentist')
    assert [e['entry_id'] for e in result['entries']] == ['e3', 'e1']
    assert 'call the dentist tomorrow' in result['entries'][1]['snippet']
    assert 'Dentist appointment' in result['entries'][0]['snippet']


@pytest.mark.asyncio
async def test_paging(app):
    result, _ = await call(app, 'search_entries', limit=1, offset=1)
    assert [e['entry_id'] for e in result['entries']] == ['e2']
    assert result['total'] == 3 and result['has_more'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('arguments, message', [
    ({'start_date': 'last tuesday'}, 'start_date must be a date in YYYY-MM-DD form'),
    ({'start_date': '2026-10-02', 'end_date': '2026-10-01'}, 'start_date is after end_date'),
    ({'limit': 0}, 'limit must be at least 1'),
    ({'offset': -1}, 'offset must not be negative'),
])
async def test_bad_arguments_are_explained(app, arguments, message):
    result, error = await call(app, 'search_entries', **arguments)
    assert result is None and message in error


# -- Reading ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_entry_returns_text_and_analysis_but_nothing_internal(app):
    result, error = await call(app, 'get_entry', entry_id='e1')
    assert error is None
    assert result['transcript'] == 'Long day. I need to call the dentist tomorrow.'
    assert result['transcript_is_cleaned'] is True
    assert result['analysis']['themes'] == ['work', 'sleep']
    assert result['analysis']['action_items'] == ['Call the dentist']
    assert result['analysis']['mood'] == {'score': 6, 'label': 'tired'}
    assert result['attachments'] == [{'filename': 'photo.jpg', 'content_type': 'image/jpeg', 'size_bytes': 2048}]
    assert result['date'] == '2026-09-29'
    assert_no_secrets(result)


@pytest.mark.asyncio
async def test_unanalysed_entry_has_no_analysis_and_raw_text(app):
    result, _ = await call(app, 'get_entry', entry_id='e3')
    assert result['analysis'] is None
    assert result['transcript'] == 'Quick note about the Dentist appointment'
    assert result['transcript_is_cleaned'] is False


@pytest.mark.asyncio
async def test_unknown_entry_is_explained(app):
    result, error = await call(app, 'get_entry', entry_id='nope')
    assert result is None and "No journal entry has entry_id 'nope'" in error


@pytest.mark.asyncio
async def test_list_tags(app):
    result, _ = await call(app, 'list_tags')
    assert result['tags'] == [{'tag': 'work', 'entry_count': 2}, {'tag': 'family', 'entry_count': 1}]


# -- Stats --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_over_a_range(app):
    result, error = await call(app, 'stats', start_date='2026-09-29', end_date='2026-10-01')
    assert error is None
    assert result['start_date'] == '2026-09-29' and result['end_date'] == '2026-10-01'
    assert result['entry_count'] == 3
    assert result['entries_awaiting_analysis'] == 1
    assert result['days_with_entries'] == 3
    assert result['longest_streak_days'] == 3
    assert result['streak_at_end_days'] == 3
    assert result['mood_average'] == 7.0
    assert result['mood_daily'] == [
        {'date': '2026-09-29', 'score': 6.0, 'entries': 1},
        {'date': '2026-09-30', 'score': 8.0, 'entries': 1}]
    assert result['themes'][0] == {'label': 'work', 'count': 2, 'last_seen': '2026-09-30'}
    assert result['people'][0] == {'label': 'Sam', 'count': 2}
    assert result['open_items'] == [
        {'kind': 'action_item', 'text': 'Call the dentist', 'date': '2026-09-29', 'entry_id': 'e1'},
        {'kind': 'open_loop', 'text': 'Decide on the trip', 'date': '2026-09-29', 'entry_id': 'e1'}]
    assert result['open_items_total'] == 2
    assert_no_secrets(result)


@pytest.mark.asyncio
async def test_stats_range_excludes_other_days(app):
    result, _ = await call(app, 'stats', start_date='2026-09-30', end_date='2026-09-30')
    assert result['entry_count'] == 1 and result['mood_average'] == 8.0
    assert result['streak_at_end_days'] == 1


# -- Writing ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_entry(app, repository, journal):
    result, error = await call(app, 'create_entry', text='  Went for a long run.  ', tags=['Health', 'health'])
    assert error is None
    created = repository.docs[result['entry']['entry_id']]
    assert created['raw_transcript'] == 'Went for a long run.'
    assert created['source'] == 'text'
    assert created['tags'] == ['health']
    assert created['title'] == 'Generated Title' and created['is_manual_title'] is False
    assert result['entry']['status'] == 'queued'
    journal._event_service.dispatch_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_entry_with_a_title_keeps_it(app, repository):
    result, _ = await call(app, 'create_entry', text='Note.', title='My own title')
    created = repository.docs[result['entry']['entry_id']]
    assert created['title'] == 'My own title' and created['is_manual_title'] is True


@pytest.mark.asyncio
async def test_set_title_marks_it_manual(app, repository):
    result, error = await call(app, 'set_title', entry_id='e2', title='  Harbour lunch ')
    assert error is None and result['entry']['title'] == 'Harbour lunch'
    assert repository.docs['e2']['is_manual_title'] is True


@pytest.mark.asyncio
async def test_update_tags_reports_what_changed(app, repository):
    result, error = await call(app, 'update_tags', entry_id='e1', add=['Travel', 'family'], remove=['WORK'])
    assert error is None
    assert result == {'entry_id': 'e1', 'tags': ['travel', 'family'], 'added': ['travel', 'family'],
                      'removed': ['work'], 'new_tags': ['travel']}
    assert repository.docs['e1']['tags'] == ['travel', 'family']


@pytest.mark.asyncio
@pytest.mark.parametrize('tool, arguments', [
    ('create_entry', {'text': 'hello'}),
    ('set_title', {'entry_id': 'e1', 'title': 'x'}),
    ('update_tags', {'entry_id': 'e1', 'add': ['x']}),
])
async def test_read_only_connections_cannot_write(app, repository, tool, arguments):
    before = json.dumps(repository.docs, default=str, sort_keys=True)
    result, error = await call(app, tool, token=READ_ONLY_TOKEN, **arguments)
    assert result is None and 'This connection is read-only' in error
    assert json.dumps(repository.docs, default=str, sort_keys=True) == before


@pytest.mark.asyncio
async def test_read_only_connections_can_read(app):
    result, error = await call(app, 'search_entries', token=READ_ONLY_TOKEN)
    assert error is None and result['total'] == 3


@pytest.mark.asyncio
@pytest.mark.parametrize('tool, arguments, message', [
    ('create_entry', {'text': '   '}, 'text must not be empty'),
    ('set_title', {'entry_id': 'e1', 'title': ' '}, 'title must not be empty'),
    ('set_title', {'entry_id': 'nope', 'title': 'x'}, "No journal entry has entry_id 'nope'"),
    ('update_tags', {'entry_id': 'e1'}, 'Give at least one tag'),
    ('update_tags', {'entry_id': 'nope', 'add': ['x']}, "No journal entry has entry_id 'nope'"),
])
async def test_bad_writes_are_explained(app, tool, arguments, message):
    result, error = await call(app, tool, **arguments)
    assert result is None and message in error


# -- Errors -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_failures_do_not_leak_details(app, journal, monkeypatch):
    async def broken(**kwargs):
        raise RuntimeError('mongo said SECRET-ERROR about entry text')

    monkeypatch.setattr(journal, 'search_entries', broken)
    result, error = await call(app, 'search_entries')
    assert result is None
    assert 'could not be completed just now (reference ' in error
    assert 'SECRET' not in error and 'mongo' not in error


# -- Service and repository ---------------------------------------------------------


@pytest.mark.asyncio
async def test_patching_an_unchanged_title_keeps_it_automatic(journal, repository):
    await journal.update_entry('e1', {'title': 'Title e1', 'tags': ['work']})
    assert repository.docs['e1']['is_manual_title'] is False
    await journal.update_entry('e1', {'title': 'Edited'})
    assert repository.docs['e1']['is_manual_title'] is True


class RecordingCollection:
    def __init__(self):
        self.calls = {}

    def find(self, query, projection=None):
        self.calls['find'] = (query, projection)
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor

        async def empty():
            return
            yield

        cursor.__aiter__ = lambda self: empty()
        return cursor

    async def count_documents(self, query):
        self.calls['count'] = query
        return 0


@pytest.mark.asyncio
async def test_repository_search_builds_a_literal_case_insensitive_filter():
    repository = object.__new__(JournalRepository)
    repository.collection = RecordingCollection()
    start, end = datetime(2026, 9, 29, 4), datetime(2026, 10, 2, 4)

    await repository.search_entries(start=start, end=end, tags=['work'], text='a.b (c)', limit=5, offset=10)

    query, projection = repository.collection.calls['find']
    assert query['created_at'] == {'$gte': start, '$lt': end}
    assert query['tags'] == {'$all': ['work']}
    pattern = {'$regex': r'a\.b\ \(c\)', '$options': 'i'}
    assert query['$or'] == [{field: pattern} for field in (
        'title', 'cleaned_transcript', 'raw_transcript', 'analysis.summary_short', 'analysis.summary_detailed')]
    assert projection == {'segments': False, 'pre_polish_transcript': False}
    assert repository.collection.calls['count'] == query
