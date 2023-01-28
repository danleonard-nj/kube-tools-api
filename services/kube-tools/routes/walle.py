

from services.walle_service import WallePhoneService
from quart import request
from framework.rest.blueprints.meta import MetaBlueprint

wallet_bp = MetaBlueprint('wallet_bp', __name__)

class PromptRequest:
    def __init__(
        self,
        data
    ):
        self.prompt = data.get('prompt')
        self.count = data.get('count')
        self.requested_by = data.get('requested_by')
        self.size = data.get('size')

@wallet_bp.configure('/api/webhook/<key>', methods=['POST'], auth_scheme='execute')
async def handle_webhook(container):
    service: WallePhoneService = container.resolve(WallePhoneService)
    
    body = await request.get_json()
    
    prompt_request  = PromptRequest(
        data=bpdy
    )
    
    return await service.execute_new_image_prompt(
        prompt=prompt_request.prompt,
        user=prompt_request.user,
        image_count=prompt_request.count)
    
    
    
    
