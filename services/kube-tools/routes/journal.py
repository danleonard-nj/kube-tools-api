from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from domain.auth import AuthPolicy
from services.journal_service import (CreateJournalCategoryRequest,
                                      CreateJournalEntryRequest,
                                      CreateJournalUnitRequest, JournalService,
                                      UpdateJournalCategoryRequest,
                                      UpdateJournalEntryRequest,
                                      UpdateJournalUnitRequest)

logger = get_logger(__name__)

journal_bp = MetaBlueprint('journal_bp', __name__)


@journal_bp.configure('/api/journal', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_entries(container):
    service: JournalService = container.resolve(JournalService)

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    return await service.get_entries(
        start_date=start_date,
        end_date=end_date)


@journal_bp.configure('/api/journal/<entry_id>', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_entry(container, entry_id: str):
    service: JournalService = container.resolve(JournalService)

    return await service.get_entry(
        entry_id=entry_id)


@journal_bp.configure('/api/journal/unit', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_units(container):
    service: JournalService = container.resolve(JournalService)

    return await service.get_units()


@journal_bp.configure('/api/journal/category', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_categories(container):
    service: JournalService = container.resolve(JournalService)

    return await service.get_categories()


@journal_bp.configure('/api/journal', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def create_entry(container):
    service: JournalService = container.resolve(JournalService)

    data = await request.get_json()

    create_request = CreateJournalEntryRequest(
        data=data)

    return await service.create_entry(
        create_request=create_request)


@journal_bp.configure('/api/journal/unit', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def create_unit(container):
    service: JournalService = container.resolve(JournalService)

    data = await request.get_json()

    create_request = CreateJournalUnitRequest(
        data=data)

    return await service.create_unit(
        create_request=create_request)


@journal_bp.configure('/api/journal/category', methods=['POST'], auth_scheme=AuthPolicy.Default)
async def create_category(container):
    service: JournalService = container.resolve(JournalService)

    data = await request.get_json()

    create_request = CreateJournalCategoryRequest(
        data=data)

    return await service.create_category(
        create_request=create_request)


@journal_bp.configure('/api/journal', methods=['PUT'], auth_scheme=AuthPolicy.Default)
async def update_entry(container):
    service: JournalService = container.resolve(JournalService)

    data = await request.get_json()

    update_request = UpdateJournalEntryRequest(
        data=data)

    return await service.update_entry(
        update_request=update_request)


@journal_bp.configure('/api/journal/unit', methods=['PUT'], auth_scheme=AuthPolicy.Default)
async def update_unit(container):
    service: JournalService = container.resolve(JournalService)

    data = await request.get_json()

    update_request = UpdateJournalUnitRequest(
        data=data)

    return await service.update_unit(
        update_request=update_request)


@journal_bp.configure('/api/journal/category', methods=['PUT'], auth_scheme=AuthPolicy.Default)
async def update_category(container):
    service: JournalService = container.resolve(JournalService)

    data = await request.get_json()

    update_request = UpdateJournalCategoryRequest(
        data=data)

    return await service.update_category(
        update_request=update_request)


@journal_bp.configure('/api/journal/<entry_id>', methods=['DELETE'], auth_scheme=AuthPolicy.Default)
async def delete_entry(container, entry_id: str):
    service: JournalService = container.resolve(JournalService)

    return await service.delete_entry(
        entry_id=entry_id)


@journal_bp.configure('/api/journal/unit/<unit_id>', methods=['DELETE'], auth_scheme=AuthPolicy.Default)
async def delete_unit(container, unit_id: str):
    service: JournalService = container.resolve(JournalService)

    return await service.delete_unit(
        unit_id=unit_id)


@journal_bp.configure('/api/journal/category/<category_id>', methods=['DELETE'], auth_scheme=AuthPolicy.Default)
async def delete_category(container, category_id: str):
    service: JournalService = container.resolve(JournalService)

    return await service.delete_category(
        category_id=category_id)
