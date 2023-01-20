

from domain.features import Feature
from domain.usage import UsageArgs
from framework.clients.feature_client import FeatureClientAsync
from quart import request
from services.usage_service import UsageService
from utilities.meta import MetaBlueprint
from framework.logger import get_logger

logger = get_logger(__name__)

webhook_bp = MetaBlueprint('webhook_bp', __name__)


@webhook_bp.configure('/api/webhook/test', methods=['POST'], auth_scheme='execute')
async def handle_webhook(container):
    data = await request.get_json()
    logger.info(f'Webook recieved: {data}')
    
    pass    
