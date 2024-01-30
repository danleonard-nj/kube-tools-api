from domain.features import Feature
from framework.clients.feature_client import FeatureClientAsync
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.acr_purge_service import AcrPurgeService

logger = get_logger(__name__)

acr_bp = MetaBlueprint('acr_bp', __name__)


@acr_bp.configure('/api/acr', methods=['POST'], auth_scheme='execute')
async def post_acr(container):
    acr_service: AcrPurgeService = container.resolve(AcrPurgeService)
    feature_client: FeatureClientAsync = container.resolve(
        FeatureClientAsync)

    if not await feature_client.is_enabled(
            feature_key=Feature.AcrPurge):
        logger.info(f'Feature is disabled')
        return feature_client.get_disabled_feature_response(
            feature_key=Feature.AcrPurge)

    days_back = request.args.get('days_back', 3)
    keep_count = request.args.get('keep_count', 3)

    images = await acr_service.purge_images(
        days_back=days_back,
        top_count=keep_count)

    return images
