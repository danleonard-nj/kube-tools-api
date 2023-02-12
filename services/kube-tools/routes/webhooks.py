

from functools import wraps
from typing import Callable, List

from framework.di.static_provider import inject_container_async
from framework.handlers.response_handler_async import response_handler
from framework.logger import get_logger
from quart import Blueprint, request

from services.sms_service import SmsService

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


webhook_bp = OpenAuthBlueprint('webhook_bp', __name__)


@webhook_bp.configure('/api/webhooks/sms', methods=['POST'])
async def handle_webhook(container):
    sms_service: SmsService = container.resolve(SmsService)

    data = await request.get_json()
    logger.info(f'SMS webook recieved: {data}')

    sms_service.handle_message(
        message=data)

    return {
        'webhook_data': data
    }
