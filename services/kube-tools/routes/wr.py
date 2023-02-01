from framework.di.static_provider import inject_container_async
from framework.handlers.response_handler_async import response_handler
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from domain.wr import CreateWellnessCheckRequest, WellnessReplyRequest
from services.wr_service import WellnessResponseService

logger = get_logger(__name__)

wr_bp = MetaBlueprint('wr_bp', __name__)


@wr_bp.configure('/api/wr/check', methods=['POST'], auth_scheme='execute')
async def post_create_check(container):
    wr_service: WellnessResponseService = container.resolve(
        WellnessResponseService)

    body = await request.get_json()

    create_request = CreateWellnessCheckRequest(
        body=body)

    return await wr_service.create_check(
        name=create_request.name,
        threshold=create_request.threshold,
        recipient=create_request.recipient,
        recipient_type=create_request.recipient_type,
        message=create_request.message)


@wr_bp.configure('/api/wr/poll', methods=['POST'], auth_scheme='execute')
async def post_poll_checks(container):
    wr_service: WellnessResponseService = container.resolve(
        WellnessResponseService)

    return await wr_service.poll()


@response_handler
@wr_bp.route('/api/wr/response', methods=['POST'])
@inject_container_async
async def post_response_webhook(container):
    wr_service: WellnessResponseService = container.resolve(
        WellnessResponseService)

    form = await request.form

    sms_response = WellnessReplyRequest(
        form=form)

    return await wr_service.handle_response(
        reply_request=sms_response)


@wr_bp.configure('/api/wr/replies', methods=['GET'], auth_scheme='execute')
async def get_replies(container):
    wr_service: WellnessResponseService = container.resolve(
        WellnessResponseService)

    return dict()


@wr_bp.configure('/api/wr/replies/sender/<sender>', methods=['GET'], auth_scheme='execute')
async def get_replies_by_sender(container, sender):
    wr_service: WellnessResponseService = container.resolve(
        WellnessResponseService)

    return await wr_service.get_last_sender_contact(
        sender=sender)
