"""Unit tests for JournalService and JournalProcessingService."""
import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

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

def make_journal_service(repo=None, processing=None):
    repo = repo or AsyncMock()
    processing = processing or AsyncMock()
    return JournalService(
        journal_repository=repo,
        journal_processing_service=processing,
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
    processing = AsyncMock()

    service = make_journal_service(repo=repo, processing=processing)

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

    with patch('services.journal_service.fire_task'):
        result = await service.create_entry(body)

    assert result['entry_id'] is not None
    assert result['status'] == JournalEntryStatus.QUEUED
    assert result['raw_transcript'] == body['raw_transcript']
    assert result['title'] == 'Morning thoughts'
    assert len(result['segments']) == 1


@pytest.mark.asyncio
async def test_create_entry_fires_processing_task():
    repo = AsyncMock()
    repo.insert_entry = AsyncMock(return_value='mongo-id')
    processing = AsyncMock()
    processing.process_entry = AsyncMock()

    service = make_journal_service(repo=repo, processing=processing)

    body = {'raw_transcript': 'Some transcript.', 'title': 'Test'}

    with patch('services.journal_service.fire_task') as mock_fire:
        await service.create_entry(body)
        mock_fire.assert_called_once()


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
    processing = AsyncMock()
    service = make_journal_service(repo=repo, processing=processing)

    with patch('services.journal_service.fire_task') as mock_fire:
        result = await service.request_processing('test-id')

    assert result['accepted'] is True
    assert result['status'] == JournalEntryStatus.QUEUED
    mock_fire.assert_called_once()


@pytest.mark.asyncio
async def test_request_processing_does_not_re_queue_when_processing():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.PROCESSING))
    service = make_journal_service(repo=repo)

    with patch('services.journal_service.fire_task') as mock_fire:
        result = await service.request_processing('test-id')

    assert result['accepted'] is True
    assert result['status'] == JournalEntryStatus.PROCESSING
    mock_fire.assert_not_called()


@pytest.mark.asyncio
async def test_request_processing_blocks_reprocess_without_force():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.PROCESSED))
    service = make_journal_service(repo=repo)

    with patch('services.journal_service.fire_task') as mock_fire:
        result = await service.request_processing('test-id', force=False)

    assert result['accepted'] is False
    mock_fire.assert_not_called()


@pytest.mark.asyncio
async def test_request_processing_allows_reprocess_with_force():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.PROCESSED))
    repo.update_entry = AsyncMock(return_value=True)
    service = make_journal_service(repo=repo)

    with patch('services.journal_service.fire_task') as mock_fire:
        result = await service.request_processing('test-id', force=True)

    assert result['accepted'] is True
    mock_fire.assert_called_once()


@pytest.mark.asyncio
async def test_request_processing_allows_retry_after_failure():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.FAILED))
    repo.update_entry = AsyncMock(return_value=True)
    service = make_journal_service(repo=repo)

    with patch('services.journal_service.fire_task') as mock_fire:
        result = await service.request_processing('test-id')

    assert result['accepted'] is True
    mock_fire.assert_called_once()


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
    gpt.generate_completion = AsyncMock()
    gpt.generate_completion.return_value = MagicMock(content=json.dumps(_GOOD_ANALYSIS))

    service = make_processing_service(repo=repo, gpt=gpt)
    await service.process_entry('test-id')

    # Should have called update_entry at least twice: mark processing, then mark processed
    assert repo.update_entry.await_count >= 2

    # Verify the final update contains PROCESSED status
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
    gpt.generate_completion = AsyncMock(side_effect=Exception('GPT failure'))

    service = make_processing_service(repo=repo, gpt=gpt)
    await service.process_entry('test-id')

    # raw_transcript must NOT have been modified in any update call
    for call in repo.update_entry.await_args_list:
        update_dict = call.args[1]
        assert 'raw_transcript' not in update_dict, 'raw_transcript must not be overwritten on failure'

    # Final update should set FAILED status
    final_call = repo.update_entry.await_args_list[-1]
    update_dict = final_call.args[1]
    assert update_dict.get('status') == JournalEntryStatus.FAILED
    assert 'GPT failure' in update_dict.get('processing.error', '')


@pytest.mark.asyncio
async def test_process_entry_skips_when_already_processing():
    repo = AsyncMock()
    repo.get_entry = AsyncMock(return_value=_make_stored_entry(status=JournalEntryStatus.PROCESSING))
    repo.update_entry = AsyncMock(return_value=True)

    gpt = AsyncMock()
    service = make_processing_service(repo=repo, gpt=gpt)
    await service.process_entry('test-id')

    repo.update_entry.assert_not_awaited()
    gpt.generate_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_entry_raises_on_empty_transcript():
    repo = AsyncMock()
    stored = _make_stored_entry(status=JournalEntryStatus.QUEUED)
    stored['raw_transcript'] = '   '
    repo.get_entry = AsyncMock(return_value=stored)
    repo.update_entry = AsyncMock(return_value=True)

    gpt = AsyncMock()
    service = make_processing_service(repo=repo, gpt=gpt)
    await service.process_entry('test-id')

    # Should have marked the entry as FAILED
    final_call = repo.update_entry.await_args_list[-1]
    update_dict = final_call.args[1]
    assert update_dict.get('status') == JournalEntryStatus.FAILED
    gpt.generate_completion.assert_not_awaited()
