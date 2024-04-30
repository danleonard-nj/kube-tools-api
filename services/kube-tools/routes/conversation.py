from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.conversation_service import ConversationService
from twilio.twiml.messaging_response import MessagingResponse


logger = get_logger(__name__)

conversation_bp = MetaBlueprint('conversation_bp', __name__)


@conversation_bp.configure('/api/conversation', methods=['POST'], auth_scheme='default')
async def post_sms_conversation(container):
    conversation_service: ConversationService = container.resolve(ConversationService)

    body = await request.get_json()

    return await conversation_service.create_conversation(
        recipient=body.get('recipient'),
        message=body.get('message'))


@conversation_bp.configure('/api/conversation/inbound', methods=['POST'], auth_scheme='default')
async def post_sms_inbound(container):
    conversation_service: ConversationService = container.resolve(ConversationService)

    data = await request.values

    # Get the message the user sent our Twilio number
    incoming_msg = data.get('Body', '').strip()

    # Get the sender's phone number
    from_number = data.get('From', '').strip()

    await conversation_service.handle_webhook(
        sender=from_number,
        message=incoming_msg)

    return '', 200


# @acr_bp.configure('/api/sms/conversation/<conversation_id>/close', methods=['PUT'], auth_scheme='default')
# async def post_sms_inbound(container, conversation_id):
#     conversation_service: ConversationService = container.resolve(ConversationService)

#     return dict()
