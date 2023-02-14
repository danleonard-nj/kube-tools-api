import json
from typing import List
from framework.logger.providers import get_logger
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from data.google.google_auth_repository import GoogleAuthRepository
from domain.google import GoogleClientScope

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

        logger.info(f'Get Google auth client')

        creds = await self.__repository.collection.find_one()

        client = Credentials.from_authorized_user_info(
            creds,
            scopes=scopes)

        client.refresh(Request())
        return client

    async def get_token(
        self,
        scopes
    ) -> Credentials:

        creds = await self.__repository.collection.find_one()

        client = Credentials.from_authorized_user_info(
            creds,
            scopes=scopes)

        client_id = creds.get('client_id')

        if (client.expired
                and client.refresh_token is not None):

            logger.info(f'Refreshing token for client: {client_id}')
            client.refresh(Request())

            updated_creds = json.loads(client.to_json())

            await self.__repository.replace(
                selector={'client_id': client_id},
                document=updated_creds)

        return client.token
