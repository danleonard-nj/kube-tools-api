from services.walle_service import WalleService

class WebhookService:
    def __init__(
        self,
        walle_service: WalleService
    ):
        self.__walle_service = walle_service

    async def handle_wallet_service(self):
        pass