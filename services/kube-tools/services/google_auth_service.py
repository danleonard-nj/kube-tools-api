from datetime import datetime
from typing import List

from data.google.google_auth_repository import GoogleAuthRepository
from framework.logger.providers import get_logger
from framework.serialization import Serializable
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = get_logger(__name__)

class AuthClient(Serializable):
    def __init__(
        self,
        token: str,
        refresh_token: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: List[str],
        expiry: str,
        timestamp: str
    ):
        self.token = token
        self.refresh_token = refresh_token
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes
        self.expiry = expiry
        self.timestamp = timestamp
        
    @staticmethod
    def from_client(
        client: Credentials
    ):
        return AuthClient(
            token=client.token,
            refresh_token=client.refresh_token,
            token_url=client.token_uri,
            client_id=client.client_id,
            client_secret=client.client_secret,
            expiry=client.expiry.isoformat(),
            timestamp=datetime.now().isoformat(),
            scopes=client.scopes
        )
    
    @staticmethod
    def from_entity(
        data: dict
    ):
        return AuthClient(
            token=data.get('token'),
            refresh_token=data.get('refresh_token'),
            token_url=data.get('token_uri'),
            client_id=data.get('client_id'),
            client_secret=data.get('client_secret'),
            scopes=data.get('scopes'),
            expiry=data.get('expiry'),
            timestamp=data.get('timestamp')
    )

    def get_selector(
        self
    ):
        return {
            'client_id': self.client_id
        }
        
    def get_credentials(
        self,
        scopes: List[str]
    ):
        return Credentials.from_authorized_user_info(
            info=self.to_dict(),
            scopes=scopes)

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
        
        auth_client = AuthClient.from_client(
            client=client)
        
        result = await self.__repository.collection.replace_one(
            auth_client.get_selector(),
            auth_client.to_dict(),
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
        entity = await self.__repository.collection.find_one()

        if entity is None:
            raise Exception(f'No Google auth client found')
        
        creds = AuthClient.from_entity(
            data=entity)

        client = creds.get_credentials(
            scopes=scopes)

        if client.expired:
            logger.info(f'Google auth client expired, refreshing')
            client.refresh(Request())

            logger.info(f'Saving Google auth client')
            await self.save_auth_client(client) 
            
        return client
