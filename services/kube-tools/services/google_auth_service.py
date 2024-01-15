from typing import List
from framework.logger.providers import get_logger
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import json
from data.google.google_auth_repository import GoogleAuthRepository
from datetime import datetime

logger = get_logger(__name__)

def dump_client(client: Credentials) -> dict:
    return {
        'token': client.token,
        'refresh_token': client.refresh_token,
        'token_uri': client.token_uri,
        'client_id': client.client_id,
        'client_secret': client.client_secret,
        'scopes': client.scopes,
        'expiry' : client.expiry.isoformat(),
        'timestamp' : datetime.now().isoformat()
    }

class GoogleAuthService:
    def __init__(
        self,
        repository: GoogleAuthRepository
    ):
        self.__repository = repository

    async def save_auth_client(
        self,
        client: Credentials
    ) -> None:
        result = await self.__repository.collection.replace_one(
            dict(client_id=client.client_id),
            dump_client(client),
            upsert=True
        )
        
        logger.info(f'Saved Google auth client: {result.raw_result}')

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

        if client.expired:
            logger.info(f'Google auth client expired, refreshing')
            client.refresh(Request())

            logger.info(f'Saving Google auth client')
            await self.save_auth_client(client) 
            
        return client
