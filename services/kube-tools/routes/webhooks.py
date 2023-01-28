

from framework.logger import get_logger
from quart import request

from framework.rest.blueprints.meta import MetaBlueprint

logger = get_logger(__name__)

webhook_bp = MetaBlueprint('webhook_bp', __name__)


@webhook_bp.configure('/api/webhooks/sms', methods=['POST'], auth_scheme='execute')
async def handle_webhook(container):
    data = await request.get_json()
    logger.info(f'Webook recieved: {data}')
    
    pass    
