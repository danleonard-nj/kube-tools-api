from framework.di.static_provider import inject_container_async
from framework.handlers.response_handler_async import response_handler
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import Blueprint, Response, request
from services.conversation_service import (ConversationService,
                                           InboundRequestValidator)

VALIDATE_TWILIO_HMAC = False

logger = get_logger(__name__)

conversation_bp = MetaBlueprint('conversation_bp', __name__)


@conversation_bp.configure('/api/conversation', methods=['POST'], auth_scheme='default')
async def post_conversation(container):
    conversation_service: ConversationService = container.resolve(ConversationService)

    body = await request.get_json()

    return await conversation_service.create_conversation(
        recipient=body.get('recipient'),
        message=body.get('message'))


@conversation_bp.configure('/api/conversation', methods=['GET'], auth_scheme='default')
async def post_conversations(container):
    conversation_service: ConversationService = container.resolve(ConversationService)

    return await conversation_service.get_conversations()


@conversation_bp.route('/api/conversation/inbound', methods=['POST'])
@response_handler
@inject_container_async
async def post_conversation_inbound(container):
    conversation_service: ConversationService = container.resolve(ConversationService)
    validator: InboundRequestValidator = container.resolve(InboundRequestValidator)

    logger.info(f'Handling inbound message from Twilio: {request.url}')

    data = await request.form

    logger.info(f'Body: {data}')
    logger.info(f'Headers: {request.headers}')

    sig = request.headers.get('X-Twilio-Signature')

    if VALIDATE_TWILIO_HMAC:
        if not await validator.validate(
                request_url=request.url,
                post_vars=data,
                twilio_signature=sig):
            logger.info('HMAC validation failed')
            return Response(None, status=403)

        await conversation_service.handle_webhook(
            sender=data.get('From', '').strip(),
            message=data.get('Body', '').strip())

    return Response(None, status=204)


@conversation_bp.configure('/api/conversation/<conversation_id>', methods=['POST'], auth_scheme='default')
async def post_conversation_id(container, conversation_id: str):
    conversation_service: ConversationService = container.resolve(ConversationService)

    body = await request.get_json()

    message = body.get('message')

    return await conversation_service.send_conversation_message(
        conversation_id=conversation_id,
        message=message)


@conversation_bp.configure('/api/conversation/<conversation_id>', methods=['GET'], auth_scheme='default')
async def get_conversation(container, conversation_id: str):
    conversation_service: ConversationService = container.resolve(ConversationService)

    return await conversation_service.get_conversation(
        conversation_id=conversation_id)


@conversation_bp.configure('/api/conversation/close', methods=['PUT'], auth_scheme='default')
async def put_conversation_close(container):
    conversation_service: ConversationService = container.resolve(ConversationService)

    body = await request.get_json()

    return await conversation_service.close_conversation(
        conversation_id=body.get('conversation_id'))