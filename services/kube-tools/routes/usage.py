from domain.features import Feature
from framework.clients.feature_client import FeatureClientAsync
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.openai_usage_service import OpenAiUsageService
from services.usage_service import UsageService

usage_bp = MetaBlueprint('usage_bp', __name__)


@usage_bp.configure('/api/usage', methods=['POST'], auth_scheme='execute')
async def usage_report(container):
    service: UsageService = container.resolve(
        UsageService)
    feature_client: FeatureClientAsync = container.resolve(
        FeatureClientAsync)

    if not await feature_client.is_enabled(
            feature_key=Feature.UsageReport):
        return feature_client.get_disabled_feature_response(
            feature_key=Feature.UsageReport)

    range_key = request.args.get('range_key')

    result = await service.send_cost_management_report(
        range_key=range_key)

    return result


@usage_bp.configure('/api/usage/openai', methods=['POST'], auth_scheme='execute')
async def post_usage_openai(container):
    service: OpenAiUsageService = container.resolve(
        OpenAiUsageService)

    return await service.send_report(
        days_back=14,
        recipients='dcl525@gmail.com'
    )
