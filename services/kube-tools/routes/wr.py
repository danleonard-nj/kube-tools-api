from functools import wraps
from typing import Callable, List
from framework.di.static_provider import inject_container_async
from framework.handlers.response_handler_async import response_handler
from framework.auth.wrappers.azure_ad_wrappers import azure_ad_authorization
from framework.logger.providers import get_logger
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request, Blueprint

from domain.wr import CreateWellnessCheckRequest, WellnessReplyRequest
from services.wr_service import WellnessResponseService

logger = get_logger(__name__)


class OpenAuthBlueprint(Blueprint):
    def __get_endpoint(self, view_function: Callable):
        return f'__route__{view_function.__name__}'

    def configure(self,  rule: str, methods: List[str]):
        def decorator(function):
            @self.route(rule, methods=methods, endpoint=self.__get_endpoint(function))
            @response_handler
            @inject_container_async
            @wraps(function)
            async def wrapper(*args, **kwargs):
                return await function(*args, **kwargs)
            return wrapper
        return decorator


wr_bp = Blueprint('wr_bp', __name__)


@wr_bp.route('/api/wellness/poll', methods=['GET'])
@response_handler
@azure_ad_authorization(scheme='read')
@inject_container_async
async def get_poll(container):
    wr_service: WellnessResponseService = container.resolve(
        WellnessResponseService)

    recipient = request.args.get('recipient')

    body = await request.get_json()


@wr_bp.route('/api/wr/webhook', methods=['POST'])
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
