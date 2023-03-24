

# from functools import wraps
# from typing import Callable, List

# from framework.di.static_provider import inject_container_async
# from framework.handlers.response_handler_async import response_handler
# from framework.logger import get_logger
# from quart import Blueprint, request

# logger = get_logger(__name__)


# class OpenAuthBlueprint(Blueprint):
#     def __get_endpoint(self, view_function: Callable):
#         return f'__route__{view_function.__name__}'

#     def configure(self,  rule: str, methods: List[str]):
#         def decorator(function):
#             @self.route(rule, methods=methods, endpoint=self.__get_endpoint(function))
#             @response_handler
#             @inject_container_async
#             @wraps(function)
#             async def wrapper(*args, **kwargs):
#                 return await function(*args, **kwargs)
#             return wrapper
#         return decorator


# webhook_bp = OpenAuthBlueprint('webhook_bp', __name__)


# @webhook_bp.configure('/api/webhooks/sms', methods=['POST'])
# async def handle_webhook(container):
#     sms_service: SmsService = container.resolve(SmsService)

#     data = await request.get_data()
#     logger.info(f'SMS webook recieved: {data}')

#     sms_service.handle_message(
#         message=data)

#     return {
#         'webhook_data': data
#     }


# @webhook_bp.configure('/api/sms/conversation', methods=['POST'])
# async def post_create_convo(container):
#     sms_service: SmsService = container.resolve(SmsService)

#     data = await request.get_json()

#     convos = await sms_service.create_conversation(
#         sender='test',
#         recipient='test',
#         application_id='test'
#     )

#     return {
#         'webhook_data': convos
#     }


# @webhook_bp.configure('/api/sms/conversation', methods=['GET'])
# async def get_convos(container):
#     sms_service: SmsService = container.resolve(SmsService)

#     data = await request.get_json()

#     convos = await sms_service.get_conversations()

#     return {
#         'webhook_data': convos
#     }


# @webhook_bp.configure('/api/sms/conversation/<convo_id>/reply', methods=['POST'])
# async def post_reply_convo(container, convo_id):
#     sms_service: SmsService = container.resolve(SmsService)

#     data = await request.get_json()

#     convos = await sms_service.reply_conversation(
#         conversation_id=convo_id,
#         message=data
#     )

#     return {
#         'webhook_data': convos
#     }
