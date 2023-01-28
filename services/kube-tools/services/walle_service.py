from framework.configuration import Configuration
from httpx import AsyncClient
import openai
from framework.logger import get_logger

logger = get_logger(__name__)

class ImageResolution:
     Low = ''
     Medium =  ''
     High = '1024x1024'

class WallePhoneService:
    def __init__(
        self,
        configuration: Configuration,
        http_client: AsyncClient,
        image_client: openai.Image
    ):       
        self.__image_client = image_client
        self.__http_client = http_client
        
    async def execute_new_image_prompt(
        self,
        prompt: str,
        user: str,
        image_count = 1
    ):
        logger.info(f'Execute image prompt: {prompt}')
        
        result = await self.__image_client.acreate(
            prompt=prompt,   
            n=image_count,
            user=user,
            size=ImageResolution.High)
        
        return result
    
    async def get_image_data(
        self,
        image_url: str
    ) -> bytes:
        data = await self.__http_client.get(
            url=image_url)
        
        return data.content