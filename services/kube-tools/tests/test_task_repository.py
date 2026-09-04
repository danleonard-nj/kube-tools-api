"""Integration tests for TaskRepository against a real MongoDB instance.

Requires MongoDB reachable at MONGO_HOST (default localhost:27017), e.g. via
`docker compose -f tests/docker-compose.yml up mongo`. These exercise real
Mongo semantics (unique indexes, atomic upserts) that cannot be verified
with mocks.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from motor.motor_asyncio import AsyncIOMotorClient

from data.google.google_tasks_repository import TaskRepository
from domain.mongo import MongoDatabase
from models.task_models import TaskOccurrence

MONGO_HOST = os.environ.get('MONGO_HOST') or 'localhost'


@pytest_asyncio.fixture
async def repository():
    client = AsyncIOMotorClient(f'mongodb://{MONGO_HOST}:27017')
    repo = TaskRepository(client)
    await repo.ensure_indexes()

    yield repo

    await client[MongoDatabase.Google].drop_collection('TaskDefinitions')
    await client[MongoDatabase.Google].drop_collection('TaskOccurrences')
    await client[MongoDatabase.Google].drop_collection('TaskDependencies')
    client.close()


@pytest.mark.asyncio
async def test_definition_and_occurrence_indexes_are_configured(repository):
    occurrence_indexes = await repository._occurrences.index_information()
    assert occurrence_indexes['definition_scheduled_unique']['unique'] is True

    dependency_indexes = await repository._dependencies.index_information()
    assert dependency_indexes['predecessor_successor_unique']['unique'] is True

    definition_indexes = await repository.collection.index_information()
    assert 'active_next_occurrence' in definition_indexes


@pytest.mark.asyncio
async def test_concurrent_claims_only_create_one_occurrence(repository):
    """The unique (task_definition_id, scheduled_for) index must reject double-claims."""
    definition_id = str(uuid.uuid4())
    scheduled_for = datetime.now(timezone.utc)

    async def claim():
        occurrence = TaskOccurrence(
            task_definition_id=definition_id,
            scheduled_for=scheduled_for,
            created_at=datetime.now(timezone.utc))
        return await repository.create_occurrence_if_missing(occurrence)

    results = await asyncio.gather(*(claim() for _ in range(10)))

    created_count = sum(1 for _, was_created in results if was_created)
    assert created_count == 1

    occurrence_ids = {occurrence.id for occurrence, _ in results}
    assert len(occurrence_ids) == 1
