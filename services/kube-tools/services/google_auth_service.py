from typing import List

from framework.logger.providers import get_logger
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from data.google.google_auth_repository import GoogleAuthRepository

logger = get_logger(__name__)


class GoogleAuthService:
    def __init__(
        self,
        repository: GoogleAuthRepository
    ):
        self.__repository = repository

    async def get_auth_client(
        self,
        scopes: List[str]
    ) -> Credentials:

        logger.info(f'Get Google auth client: {scopes}')

        # The only record in the collection should be the
        # auth config
        creds = await self.__repository.collection.find_one()

        client = Credentials.from_authorized_user_info(
            creds,
            scopes=scopes)

        client.refresh(Request())
        return client
