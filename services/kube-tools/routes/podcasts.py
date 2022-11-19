from framework.auth.wrappers.azure_ad_wrappers import azure_ad_authorization
from framework.clients.feature_client import FeatureClientAsync
from framework.dependency_injection.provider import inject_container_async
from framework.handlers.response_handler_async import response_handler
from framework.logger.providers import get_logger
from quart import Blueprint
from services.podcast_service import PodcastService
from domain.features import Feature

podcasts_bp = Blueprint('podcasts_bp', __name__)

logger = get_logger(__name__)


@podcasts_bp.route('/api/podcasts', endpoint='get_podcasts')
@response_handler
@azure_ad_authorization(scheme='execute')
@inject_container_async
async def get_podcasts(container):
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
