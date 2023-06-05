

from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.chat_gpt_proxy_service import ChatGptProxyService

chatgpt_bp = MetaBlueprint('chatgpt_bp', __name__)


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
