"""Unit tests for JournalService and JournalProcessingService."""
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from domain.journal import (
    JournalEntry,
    JournalEntryStatus,
    JournalProcessingMetadata,
    JournalSegment,
    JournalSource,
)
from services.journal_processing_service import JournalProcessingService
from services.journal_service import JournalService, JournalServiceError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_journal_service(repo=None, event_service=None, identity_client=None, configuration=None, gpt_client=None):
    repo = repo or AsyncMock()
    event_service = event_service or AsyncMock()
    identity_client = identity_client or AsyncMock()
    identity_client.get_token = AsyncMock(return_value='test-token')
    if configuration is None:
        configuration = MagicMock()
        configuration.chatgpt = {'base_url': 'https://api.dan-leonard.com'}
    if gpt_client is None:
        gpt_client = AsyncMock()
        gpt_client.generate_completion = AsyncMock(return_value=MagicMock(content=''))
    return JournalService(
        journal_repository=repo,
        event_service=event_service,
        identity_client=identity_client,
        configuration=configuration,
        gpt_client=gpt_client,
    )


def make_processing_service(repo=None, gpt=None):
    repo = repo or AsyncMock()
    gpt = gpt or AsyncMock()
    return JournalProcessingService(
        journal_repository=repo,
        gpt_client=gpt,
    )


def _make_stored_entry(entry_id='test-id', status=JournalEntryStatus.CREATED):
    return {
        'entry_id': entry_id,
        'created_at': datetime.utcnow(),
        'updated_at': datetime.utcnow(),
        'title': 'Test Entry',
        'source': JournalSource.VOICE,
        'status': status,
        'segments': [],
        'raw_transcript': 'Hello world from this voice note.',
        'cleaned_transcript': None,
        'analysis': None,
        'processing': {
            'requested_at': datetime.utcnow(),
            'started_at': None,
            'completed_at': None,
            'failed_at': None,
            'error': None,
            'attempt_count': 0,
        },
    }


# ---------------------------------------------------------------------------
# JournalService.create_entry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_entry_returns_dict_with_entry_id():
    repo = AsyncMock()
    repo.insert_entry = AsyncMock(return_value='mongo-id')
    event_service = AsyncMock()

    service = make_journal_service(repo=repo, event_service=event_service)

    body = {
        'title': 'Morning thoughts',
        'source': 'voice',
        'raw_transcript': 'Today I woke up feeling okay.',
        'segments': [
            {
                'clip_id': 'clip-1',
                'started_at': '2026-04-28T08:00:00Z',
                'duration_seconds': 30,
                'transcript': 'Today I woke up feeling okay.',
            }
        ],
    }

    result = await service.create_entry(body)

    assert result['entry_id'] is not None
    assert result['status'] == JournalEntryStatus.QUEUED
    assert result['raw_transcript'] == body['raw_transcript']
    assert result['title'] == 'Morning thoughts'
    assert len(result['segments']) == 1


@pytest.mark.asyncio
async def test_create_entry_dispatches_processing_event():
    repo = AsyncMock()
    repo.insert_entry = AsyncMock(return_value='mongo-id')
    event_service = AsyncMock()

    service = make_journal_service(repo=repo, event_service=event_service)

    body = {'raw_transcript': 'Some transcript.', 'title': 'Test'}

    await service.create_entry(body)
    event_service.dispatch_event.assert_awaited_once()


# ---------------------------------------------------------------------------
# JournalService auto-title on create
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_entry_generates_title_when_no_manual_title():
    repo = AsyncMock()
    repo.insert_entry = AsyncMock(return_value='mongo-id')
    repo.update_entry = AsyncMock(return_value=True)

    gpt = AsyncMock()
    gpt.generate_completion = AsyncMock(return_value=MagicMock(content='Calm morning reflections'))

    service = make_journal_service(repo=repo, gpt_client=gpt)
    result = await service.create_entry({'raw_transcript': 'Today was a calm morning.'})

    gpt.generate_completion.assert_awaited_once()
    assert result['title'] == 'Calm morning reflections'
    assert result['is_manual_title'] is False
    # Confirm title was persisted
    repo.update_entry.assert_awaited_once_with(result['entry_id'], {'title': 'Calm morning reflections'})


@pytest.mark.asyncio
async def test_create_entry_skips_title_generation_when_manual_title_provided():
    repo = AsyncMock()
    repo.insert_entry = AsyncMock(return_value='mongo-id')

    gpt = AsyncMock()
    gpt.generate_completion = AsyncMock()

    service = make_journal_service(repo=repo, gpt_client=gpt)
    result = await service.create_entry({
        'raw_transcript': 'Today was a calm morning.',
        'title': 'My custom title',
    })

    gpt.generate_completion.assert_not_awaited()
    assert result['title'] == 'My custom title'
    assert result['is_manual_title'] is True


@pytest.mark.asyncio
async def test_create_entry_continues_when_auto_title_fails():
    repo = AsyncMock()
    repo.insert_entry = AsyncMock(return_value='mongo-id')

    gpt = AsyncMock()
    gpt.generate_completion = AsyncMock(side_effect=Exception('LLM error'))

    service = make_journal_service(repo=repo, gpt_client=gpt)
    result = await service.create_entry({'raw_transcript': 'Some text.'})

    # Entry still created successfully, title just stays None
    assert result['entry_id'] is not None
    assert result['title'] is None
    assert result['is_manual_title'] is False
    # No update_entry call for title since generation failed
    repo.update_entry.assert_not_awaited()


# ---------------------------------------------------------------------------
# JournalService.refresh_title
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_title_returns_none_when_entry_not_found():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=None)
    service = make_journal_service(repo=repo)

    result = await service.refresh_title('missing-id')
    assert result is None


@pytest.mark.asyncio
async def test_refresh_title_skips_update_when_manual_title_set():
    repo = AsyncMock()
    stored = _make_stored_entry()  # has is_manual_title=True
    stored['is_manual_title'] = True
    repo.get_entry = AsyncMock(return_value=stored)

    gpt = AsyncMock()
    gpt.generate_completion = AsyncMock()

    service = make_journal_service(repo=repo, gpt_client=gpt)
    result = await service.refresh_title('test-id')

    gpt.generate_completion.assert_not_awaited()
    assert result is not None  # returns existing entry unchanged


@pytest.mark.asyncio
async def test_refresh_title_updates_when_no_manual_title():
    stored = _make_stored_entry()
    stored['title'] = None
    stored['is_manual_title'] = False

    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=stored)
    repo.update_entry = AsyncMock(return_value=True)

    gpt = AsyncMock()
    gpt.generate_completion = AsyncMock(return_value=MagicMock(content='New generated title'))

    service = make_journal_service(repo=repo, gpt_client=gpt)
    await service.refresh_title('test-id')

    gpt.generate_completion.assert_awaited_once()
    repo.update_entry.assert_awaited_once_with('test-id', {'title': 'New generated title'})


# ---------------------------------------------------------------------------
# JournalService.get_entry / list_entries
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_entry_returns_none_when_not_found():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=None)
    service = make_journal_service(repo=repo)

    result = await service.get_entry('missing-id')
    assert result is None


@pytest.mark.asyncio
async def test_get_entry_returns_serialized_entry():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry())
    service = make_journal_service(repo=repo)

    result = await service.get_entry('test-id')
    assert result is not None
    assert result['entry_id'] == 'test-id'
    assert result['raw_transcript'] == 'Hello world from this voice note.'


@pytest.mark.asyncio
async def test_list_entries_returns_list():
    repo = AsyncMock()
    repo.list_recent = AsyncMock(return_value=[_make_stored_entry(), _make_stored_entry(entry_id='id-2')])
    service = make_journal_service(repo=repo)

    result = await service.list_entries()
    assert len(result) == 2


# ---------------------------------------------------------------------------
# JournalService.request_processing (idempotency)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_processing_queues_when_created():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.CREATED))
    repo.update_entry = AsyncMock(return_value=True)
    event_service = AsyncMock()
    service = make_journal_service(repo=repo, event_service=event_service)

    result = await service.request_processing('test-id')

    assert result['accepted'] is True
    assert result['status'] == JournalEntryStatus.QUEUED
    event_service.dispatch_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_processing_does_not_re_queue_when_processing():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.PROCESSING))
    event_service = AsyncMock()
    service = make_journal_service(repo=repo, event_service=event_service)

    result = await service.request_processing('test-id')

    assert result['accepted'] is True
    assert result['status'] == JournalEntryStatus.PROCESSING
    event_service.dispatch_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_processing_blocks_reprocess_without_force():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.PROCESSED))
    event_service = AsyncMock()
    service = make_journal_service(repo=repo, event_service=event_service)

    result = await service.request_processing('test-id', force=False)

    assert result['accepted'] is False
    event_service.dispatch_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_processing_allows_reprocess_with_force():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.PROCESSED))
    repo.update_entry = AsyncMock(return_value=True)
    event_service = AsyncMock()
    service = make_journal_service(repo=repo, event_service=event_service)

    result = await service.request_processing('test-id', force=True)

    assert result['accepted'] is True
    event_service.dispatch_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_processing_allows_retry_after_failure():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.FAILED))
    repo.update_entry = AsyncMock(return_value=True)
    event_service = AsyncMock()
    service = make_journal_service(repo=repo, event_service=event_service)

    result = await service.request_processing('test-id')

    assert result['accepted'] is True
    event_service.dispatch_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_processing_raises_when_not_found():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=None)
    service = make_journal_service(repo=repo)

    with pytest.raises(JournalServiceError):
        await service.request_processing('nonexistent')


# ---------------------------------------------------------------------------
# JournalProcessingService.process_entry
# ---------------------------------------------------------------------------

_GOOD_ANALYSIS = {
    'cleaned_transcript': 'I woke up feeling okay today.',
    'summary': 'A calm morning.',
    'bullets': ['Felt okay'],
    'themes': ['morning', 'mood'],
    'mood': {'score': 6, 'label': 'neutral', 'confidence': 0.8},
    'symptoms': [],
    'action_items': [],
    'risk_flags': {'crisis_language': False, 'medical_concern': False},
}


@pytest.mark.asyncio
async def test_process_entry_success_updates_analysis_and_status():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.QUEUED))
    repo.update_entry = AsyncMock(return_value=True)

    gpt = AsyncMock()
    gpt.generate_response = AsyncMock()
    gpt.generate_response.return_value = MagicMock(text=json.dumps(_GOOD_ANALYSIS))

    service = make_processing_service(repo=repo, gpt=gpt)
    await service.process_entry('test-id')

    assert repo.update_entry.await_count >= 2

    final_call_kwargs = repo.update_entry.await_args_list[-1]
    update_dict = final_call_kwargs.args[1]
    assert update_dict.get('status') == JournalEntryStatus.PROCESSED
    assert 'analysis' in update_dict
    assert update_dict.get('cleaned_transcript') == 'I woke up feeling okay today.'


@pytest.mark.asyncio
async def test_process_entry_failure_preserves_raw_transcript_and_marks_failed():
    repo = AsyncMock()
    stored = _make_stored_entry(status=JournalEntryStatus.QUEUED)
    repo.get_entry = AsyncMock(return_value=stored)
    repo.update_entry = AsyncMock(return_value=True)

    gpt = AsyncMock()
    gpt.generate_response = AsyncMock(side_effect=Exception('GPT failure'))

    service = make_processing_service(repo=repo, gpt=gpt)
    await service.process_entry('test-id')

    for call in repo.update_entry.await_args_list:
        update_dict = call.args[1]
        assert 'raw_transcript' not in update_dict, 'raw_transcript must not be overwritten on failure'

    final_call = repo.update_entry.await_args_list[-1]
    update_dict = final_call.args[1]
    assert update_dict.get('status') == JournalEntryStatus.FAILED
    assert 'GPT failure' in update_dict.get('processing.error', '')
