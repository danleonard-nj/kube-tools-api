
from domain.exceptions import AcrPurgeServiceParameterException
from domain.features import Feature
from framework.clients.feature_client import FeatureClientAsync
from framework.logger.providers import get_logger
from services.acr_service import AcrService
from utilities.meta import MetaBlueprint

logger = get_logger(__name__)

acr_bp = MetaBlueprint('acr_bp', __name__)


@acr_bp.configure('/api/acr', methods=['POST'], auth_scheme='execute')
async def acr_run(container):
    acr_service: AcrService = container.resolve(AcrService)
    feature_client: FeatureClientAsync = container.resolve(FeatureClientAsync)

    if not await feature_client.is_enabled(
            feature_key=Feature.AcrPurge):

        logger.info(f'Feature is disabled')
        return feature_client.get_disabled_feature_response(
            feature_key=Feature.AcrPurge)

    return await acr_service.purge_acr()
