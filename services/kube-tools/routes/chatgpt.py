from typing import Tuple

from framework.rest.blueprints.meta import MetaBlueprint
from quart import request

from services.chat_gpt_proxy_service import ChatGptProxyService

chatgpt_bp = MetaBlueprint('chatgpt_bp', __name__)


def get_history_args() -> Tuple[str, str, str]:
    return (
        request.args.get('start_timestamp'),
        request.args.get('end_timestamp'),
        request.args.get('endpoint')
    )


@chatgpt_bp.configure('/api/chatgpt/completions', methods=['POST'], auth_scheme='default')
async def post_completions(container):
    service: ChatGptProxyService = container.resolve(
        ChatGptProxyService)

    body = await request.get_json()

    return await service.proxy_request(
        endpoint='/v1/completions',
        method='POST',
        request_body=body)


@chatgpt_bp.configure('/api/chatgpt/engines', methods=['GET'], auth_scheme='default')
async def post_engines(container):
    service: ChatGptProxyService = container.resolve(
        ChatGptProxyService)

    body = await request.get_json()

    return await service.proxy_request(
        endpoint='/v1/engines',
        method='GET',
        request_body=body)


@chatgpt_bp.configure('/api/chatgpt/images/generations', methods=['POST'], auth_scheme='default')
async def post_generate_images(container):
    service: ChatGptProxyService = container.resolve(
        ChatGptProxyService)

    body = await request.get_json()

    return await service.proxy_request(
        endpoint='/v1/images/generations',
        method='POST',
        request_body=body)


@chatgpt_bp.configure('/api/chatgpt/history', methods=['GET'], auth_scheme='default')
async def get_history(container):
    service: ChatGptProxyService = container.resolve(
        ChatGptProxyService)

    (start_timestamp,
     end_timestamp,
     endpoint) = get_history_args()

    return await service.get_history(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        endpoint=endpoint)


@chatgpt_bp.configure('/api/chatgpt/history/endpoints', methods=['GET'], auth_scheme='default')
async def get_history_grouped(container):
    service: ChatGptProxyService = container.resolve(
        ChatGptProxyService)

    (start_timestamp,
     end_timestamp,
     endpoint) = get_history_args()

    return await service.get_endpoint_history(
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        endpoint=endpoint)
