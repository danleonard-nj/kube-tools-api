from domain.auth import AuthPolicy
from domain.features import Feature
from framework.clients.feature_client import FeatureClientAsync
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from services.podcast_service import PodcastService

podcasts_bp = MetaBlueprint('podcasts_bp', __name__)

logger = get_logger(__name__)


@podcasts_bp.configure('/api/podcasts', methods=['GET', 'POST'], auth_scheme=AuthPolicy.Execute)
async def sync_podcasts(container):
    podcast_service: PodcastService = container.resolve(
        PodcastService)
    feature_client: FeatureClientAsync = container.resolve(
        FeatureClientAsync)

    if not await feature_client.is_enabled(
            feature_key=Feature.PodcastSync):
        logger.info(f'Feature is disabled')
        return feature_client.get_disabled_feature_response(
            feature_key=Feature.PodcastSync)

    result = await podcast_service.sync()
    return result


@podcasts_bp.configure('/api/podcasts/shows', methods=['GET'], auth_scheme=AuthPolicy.Default)
async def get_podcasts(container):
    podcast_service: PodcastService = container.resolve(
        PodcastService)
    
    return await podcast_service.get_podcasts()
