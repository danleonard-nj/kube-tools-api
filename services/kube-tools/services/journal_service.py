

import uuid
from datetime import datetime

from dateutil import parser
from framework.exceptions.nulls import ArgumentNullException
from framework.logger.providers import get_logger
from framework.serialization.serializer import Serializable

from data.journal_repository import (JournalCategoryRepository,
                                     JournalEntryRepository,
                                     JournalUnitRepository)
from domain.journal import JournalCategory, JournalEntry, JournalUnit
from utilities.utils import DateTimeUtil


def parse_date(
    value: str | int
) -> datetime:
    if isinstance(value, str):
        return parser.parse(value)
    return datetime.fromtimestamp(value)


logger = get_logger(__name__)


# TODO: Move to rest domain
class CreateJournalEntryRequest(Serializable):
    def __init__(
        self,
        data: dict
    ):
        self.unit_id = data.get('unit_id')
        self.quantity = data.get('quantity')
        self.note = data.get('note')


class UpdateJournalEntryRequest(Serializable):
    def __init__(
        self,
        data: dict
    ):
        self.category_id = data.get('category_id')
        self.unit_id = data.get('unit_id')
        self.quantity = data.get('quantity')
        self.note = data.get('note')


class CreateJournalUnitRequest(Serializable):
    def __init__(
        self,
        data: dict
    ):
        self.unit_name = data.get('unit_name')
        self.symbol_name = data.get('symbol_name')


class UpdateJournalUnitRequest(Serializable):
    def __init__(
        self,
        data: dict
    ):
        self.unit_id = data.get('unit_id')
        self.unit_name = data.get('unit_name')
        self.symbol_name = data.get('symbol_name')


class CreateJournalCategoryRequest(Serializable):
    def __init__(
        self,
        data: dict
    ):
        self.category_name = data.get('category_name')
        self.symbol_name = data.get('symbol_name')


class UpdateJournalCategoryRequest(Serializable):
    def __init__(
        self,
        data: dict
    ):
        self.category_id = data.get('category_id')
        self.category_name = data.get('category_name')
        self.symbol_name = data.get('symbol_name')


class DeleteResponse(Serializable):
    def __init__(
        self,
        success: bool,
        count: int
    ):
        self.success = success
        self.count = count


class JournalService:
    def __init__(
        self,
        entry_repository: JournalEntryRepository,
        category_repository: JournalCategoryRepository,
        unit_repository: JournalUnitRepository
    ):
        self.__entry_repository = entry_repository
        self.__category_repository = category_repository
        self.__unit_repository = unit_repository

    async def get_entries(
        self,
        start_date: str | int,
        end_date: str | int,
    ) -> list[JournalEntry]:

        ArgumentNullException.if_none(start_date, 'start_date')
        ArgumentNullException.if_none(end_date, 'end_date')

        start_date = parse_date(start_date)
        end_date = parse_date(end_date)

        entities = await self.__entry_repository.get_entries(
            start_timestamp=int(start_date.timestamp()),
            end_timestamp=(end_date.timestamp())
        )

        entries = [JournalEntry.from_entity(entity)
                   for entity in entities]

        return entries

    async def get_entry(
        self,
        entry_id: str
    ) -> JournalEntry:

        ArgumentNullException.if_none_or_whitespace(entry_id, 'entry_id')

        entity = await self.__entry_repository.get({
            'entry_id': entry_id
        })

        if entity is None:
            raise Exception(f'Entry not found: {entry_id}')

        entry = JournalEntry.from_entity(entity)

        return entry

    async def get_categories(
        self
    ):
        logger.info('Getting categories')
        entities = await self.__category_repository.get_all()

        categories = [JournalCategory.from_entity(entity)
                      for entity in entities]

        logger.info(f'Categories: {categories}')

        return categories

    async def get_units(
        self
    ) -> list[JournalUnit]:

        logger.info(f'Getting units')
        entities = await self.__unit_repository.get_all()

        units = [JournalUnit.from_entity(entity)
                 for entity in entities]

        logger.info(f'Units: {units}')

        return units

    async def create_entry(
        self,
        create_request: CreateJournalEntryRequest
    ):
        ArgumentNullException.if_none(create_request, 'create_request')
        ArgumentNullException.if_none_or_whitespace(
            create_request.category_id, 'category_id')
        ArgumentNullException.if_none_or_whitespace(
            create_request.unit_id, 'unit_id')
        ArgumentNullException.if_none_or_whitespace(
            create_request.quantity, 'quantity')

        logger.info(f'Creating entry: {create_request.to_dict()}')

        entry = JournalEntry(
            entry_id=str(uuid.uuid4()),
            entry_date=datetime.now(),
            category_id=create_request.category_id,
            unit_id=create_request.unit_id,
            quantity=create_request.quantity,
            note=create_request.note,
            timestamp=DateTimeUtil.now()
        )

        insert_result = await self.__entry_repository.insert(
            document=entry.to_dict())

        logger.info(f'Insert result: {insert_result.inserted_id}')

    async def create_category(
        self,
        create_request: CreateJournalCategoryRequest
    ):
        ArgumentNullException.if_none(create_request, 'create_request')
        ArgumentNullException.if_none_or_whitespace(
            create_request.category_name, 'category_name')

        category = JournalCategory(
            category_id=str(uuid.uuid4()),
            category_name=create_request.category_name,
            symbol_name=create_request.symbol_name,
            timestamp=DateTimeUtil.timestamp()
        )

        await self.__category_repository.insert(
            document=category.to_dict())

    async def create_unit(
        self,
        create_request: CreateJournalUnitRequest
    ):

        ArgumentNullException.if_none(create_request, 'create_request')
        ArgumentNullException.if_none_or_whitespace(
            create_request.unit_name, 'unit_name')

        unit = JournalUnit(
            unit_id=str(uuid.uuid4()),
            unit_name=create_request.unit_name,
            symbol_name=create_request.symbol_name,
            timestamp=DateTimeUtil.timestamp()
        )

        await self.__unit_repository.insert(
            document=unit.to_dict())

    async def update_entry(
        self,
        update_request: UpdateJournalEntryRequest
    ):

        existing_record = await self.__entry_repository.get({
            'entry_id': update_request.entry_id
        })

        if existing_record is None:
            raise Exception(f'Entry not found: {update_request.entry_id}')

        updated = JournalEntry.from_entity(
            data=existing_record | update_request.to_dict())

        logger.info(f'Updating entry: {updated.to_dict()}')

        return updated

    async def update_category(
        self,
        update_request: UpdateJournalCategoryRequest
    ):
        ArgumentNullException.if_none(update_request, 'update_request')
        ArgumentNullException.if_none_or_whitespace(
            update_request.category_id, 'category_id')
        ArgumentNullException.if_none_or_whitespace(
            update_request.category_name, 'category_name')

        existing_record = await self.__category_repository.get({
            'category_id': update_request.category_id
        })

        if existing_record is None:
            raise Exception(
                f'Category not found: {update_request.category_id}')

        updated = JournalCategory.from_entity(
            data=existing_record | update_request.to_dict())

        logger.info(f'Updating category: {updated.to_dict()}')

        return updated

    async def update_unit(
        self,
        update_request: UpdateJournalUnitRequest
    ):

        existing_record = await self.__unit_repository.get({
            'unit_id': update_request.unit_id
        })

        if existing_record is None:
            raise Exception(f'Unit not found: {update_request.unit_id}')

        updated = JournalUnit.from_entity(
            data=existing_record | update_request.to_dict())

        logger.info(f'Updating unit: {updated.to_dict()}')

        return updated

    async def delete_unit(
        self,
        unit_id: str
    ):
        ArgumentNullException.if_none_or_whitespace(unit_id, 'unit_id')

        delete_result = await self.__unit_repository.delete({
            'unit_id': unit_id
        })

        return DeleteResponse(
            success=delete_result.acknowledged,
            count=delete_result.deleted_count)

    async def delete_entry(
        self,
        entry_id: str
    ):
        ArgumentNullException.if_none_or_whitespace(entry_id, 'entry_id')

        delete_result = await self.__entry_repository.delete({
            'entry_id': entry_id
        })

        return DeleteResponse(
            success=delete_result.acknowledged,
            count=delete_result.deleted_count)

    async def delete_category(
        self,
        category_id: str
    ):
        ArgumentNullException.if_none_or_whitespace(category_id, 'category_id')

        delete_result = await self.__category_repository.delete({
            'category_id': category_id
        })

        return DeleteResponse(
            success=delete_result.acknowledged,
            count=delete_result.deleted_count)
