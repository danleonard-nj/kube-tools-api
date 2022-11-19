from framework.rest.blueprints.meta import MetaBlueprint
from services.reverb_service import ReverbListingProcessor, ReverbListingService, ReverbListingSyncService

reverb_bp = MetaBlueprint('reverb_bp', __name__)


@reverb_bp.configure('/api/reverb/sync/products', methods=['POST'], auth_scheme='default')
async def reverb_sync_products(container):
    service: ReverbListingSyncService = container.resolve(
        ReverbListingSyncService)

    return await service.get_listings()


@reverb_bp.configure('/api/reverb/process', methods=['POST'], auth_scheme='default')
async def reverb_process(container):
    service: ReverbListingProcessor = container.resolve(ReverbListingProcessor)

    return await service.process()
