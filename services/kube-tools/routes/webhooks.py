

from framework.logger import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from services.sms_service import SmsService

logger = get_logger(__name__)

webhook_bp = MetaBlueprint('webhook_bp', __name__)


@webhook_bp.configure('/api/webhooks/sms', methods=['POST'], auth_scheme='execute')
async def handle_webhook(container):
    sms_service: SmsService = container.resolve(SmsService)

    data = await request.get_json()
    logger.info(f'SMS webook recieved: {data}')

    sms_service.handle_message(
        message=data)
