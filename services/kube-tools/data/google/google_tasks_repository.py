"""Mongo persistence for the Google Tasks feature.

Google Tasks remains the source of truth for ordinary one-time tasks. This
repository only stores the pieces needed for locally-managed recurrence and
future task-chain support, across three collections in the ``Google``
database (alongside ``CalendarEvent`` and ``Auth``)::

    TaskDefinitions
        {_id, google_task_list_id, title, notes, starts_at, recurrence,
         next_occurrence_at, last_materialized_at, active, created_at, updated_at}

    TaskOccurrences
        {_id, task_definition_id, google_task_id, scheduled_for,
         completed_at, triggered_by_occurrence_id, created_at}

        Unique compound index: (task_definition_id ASC, scheduled_for ASC).
        This is the idempotency boundary that makes concurrent polls safe.

    TaskDependencies
        {_id, predecessor_task_definition_id, successor_task_definition_id,
         trigger, delay_seconds, created_at}

        Unique compound index: (predecessor_task_definition_id ASC,
        successor_task_definition_id ASC).
"""
from datetime import datetime

import pymongo
from bson import ObjectId
from pymongo import AsyncMongoClient
from pymongo import ReturnDocument

from domain.mongo import MongoDatabase
from framework.logger import get_logger
from framework.mongo.mongo_repository import MongoRepositoryAsync
from models.task_models import TaskDefinition, TaskDependency, TaskOccurrence

logger = get_logger(__name__)

_DEFINITIONS_COLLECTION = 'TaskDefinitions'
_OCCURRENCES_COLLECTION = 'TaskOccurrences'
_DEPENDENCIES_COLLECTION = 'TaskDependencies'


def _definition_from_doc(doc: dict) -> TaskDefinition:
    doc['id'] = str(doc.pop('_id'))
    return TaskDefinition.model_validate(doc)


def _occurrence_from_doc(doc: dict) -> TaskOccurrence:
    doc['id'] = str(doc.pop('_id'))
    return TaskOccurrence.model_validate(doc)


def _dependency_from_doc(doc: dict) -> TaskDependency:
    doc['id'] = str(doc.pop('_id'))
    return TaskDependency.model_validate(doc)


class TaskRepository(MongoRepositoryAsync):
    def __init__(self, client: AsyncMongoClient):
        super().__init__(
            client=client,
            database=MongoDatabase.Google,
            collection=_DEFINITIONS_COLLECTION)

        self._occurrences = client[MongoDatabase.Google][_OCCURRENCES_COLLECTION]
        self._dependencies = client[MongoDatabase.Google][_DEPENDENCIES_COLLECTION]

    async def ensure_indexes(self) -> None:
        await self.collection.create_index(
            [('active', pymongo.ASCENDING),
             ('next_occurrence_at', pymongo.ASCENDING)],
            name='active_next_occurrence')

        await self._occurrences.create_index(
            [('task_definition_id', pymongo.ASCENDING),
             ('scheduled_for', pymongo.ASCENDING)],
            unique=True,
            name='definition_scheduled_unique')

        await self._occurrences.create_index(
            [('google_task_id', pymongo.ASCENDING)],
            name='google_task_id_lookup')

        await self._dependencies.create_index(
            [('predecessor_task_definition_id', pymongo.ASCENDING),
             ('successor_task_definition_id', pymongo.ASCENDING)],
            unique=True,
            name='predecessor_successor_unique')

        await self._dependencies.create_index(
            [('successor_task_definition_id', pymongo.ASCENDING)],
            name='successor_lookup')

        logger.info('Task repository indexes ensured')

    # ------------------------------------------------------------------
    # Task definitions
    # ------------------------------------------------------------------

    async def create_definition(
        self,
        definition: TaskDefinition
    ) -> TaskDefinition:
        document = definition.model_dump(exclude={'id'})
        result = await self.collection.insert_one(document)

        definition.id = str(result.inserted_id)
        return definition

    async def update_definition(
        self,
        definition: TaskDefinition
    ) -> TaskDefinition:
        await self.collection.update_one(
            {'_id': ObjectId(definition.id)},
            {'$set': definition.model_dump(exclude={'id'})})

        return definition

    async def delete_definition(
        self,
        definition_id: str
    ) -> None:
        await self.collection.delete_one({'_id': ObjectId(definition_id)})

    async def get_definition(
        self,
        definition_id: str
    ) -> TaskDefinition | None:
        doc = await self.collection.find_one({'_id': ObjectId(definition_id)})
        if doc is None:
            return None
        return _definition_from_doc(doc)

    async def get_due_definitions(
        self,
        through: datetime,
        limit: int
    ) -> list[TaskDefinition]:
        cursor = self.collection.find(
            {'active': True, 'next_occurrence_at': {'$lte': through}}
        ).sort('next_occurrence_at', pymongo.ASCENDING).limit(limit)

        return [_definition_from_doc(doc) async for doc in cursor]

    # ------------------------------------------------------------------
    # Task occurrences
    # ------------------------------------------------------------------

    async def create_occurrence_if_missing(
        self,
        occurrence: TaskOccurrence
    ) -> tuple[TaskOccurrence, bool]:
        """Atomically claim an occurrence via the unique (definition, scheduled_for) index."""
        selector = {
            'task_definition_id': occurrence.task_definition_id,
            'scheduled_for': occurrence.scheduled_for,
        }
        on_insert = occurrence.model_dump(exclude={'id'} | selector.keys())

        before = await self._occurrences.find_one_and_update(
            selector,
            {'$setOnInsert': on_insert},
            upsert=True,
            return_document=ReturnDocument.BEFORE)

        was_created = before is None

        doc = before
        if was_created:
            doc = await self._occurrences.find_one(selector)

        return _occurrence_from_doc(doc), was_created

    async def set_occurrence_google_task_id(
        self,
        occurrence_id: str,
        google_task_id: str
    ) -> None:
        await self._occurrences.update_one(
            {'_id': ObjectId(occurrence_id)},
            {'$set': {'google_task_id': google_task_id}})

    async def delete_occurrence(
        self,
        occurrence_id: str
    ) -> None:
        """Remove a claimed occurrence whose Google Task creation failed, so a future poll can retry."""
        await self._occurrences.delete_one({'_id': ObjectId(occurrence_id)})

    # ------------------------------------------------------------------
    # Task dependencies
    # ------------------------------------------------------------------

    async def create_dependency(
        self,
        dependency: TaskDependency
    ) -> TaskDependency:
        document = dependency.model_dump(exclude={'id'})
        result = await self._dependencies.insert_one(document)

        dependency.id = str(result.inserted_id)
        return dependency

    async def get_successor_dependencies(
        self,
        predecessor_task_definition_id: str
    ) -> list[TaskDependency]:
        cursor = self._dependencies.find(
            {'predecessor_task_definition_id': predecessor_task_definition_id})

        return [_dependency_from_doc(doc) async for doc in cursor]
