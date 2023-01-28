from services.walle_service import WallePhoneService

class WebhookService:
    def __init__(
        self,
        walle_service: WallePhoneService
    ):
        self.__walle_service = walle_service

    async def handle_wallet_service(self):
        pass