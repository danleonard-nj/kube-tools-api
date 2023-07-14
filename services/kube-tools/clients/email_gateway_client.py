from typing import Any, Dict, List

import httpx
from framework.configuration import Configuration
from framework.logger.providers import get_logger
from httpx import AsyncClient

from clients.identity_client import IdentityClient
from domain.auth import ClientScope
from domain.email_gateway import EmailGatewayRequest
from domain.rest import AuthorizationHeader

logger = get_logger(__name__)


class EmailGatewayClient:
    def __init__(
        self,
        configuration: Configuration,
        identity_client: IdentityClient,
        http_client: AsyncClient
    ):
        self.__http_client = http_client
        self.__identity_client = identity_client
        self.__base_url = configuration.gateway.get(
            'email_gateway_base_url')

    async def send_email(
        self,
        subject: str,
        recipient: str,
        message: str
    ):
        endpoint = f'{self.__base_url}/api/email/send'
        logger.info(f'Endpoint: {endpoint}')

        content = EmailGatewayRequest(
            recipient=recipient,
            subject=subject,
            body=message)

        headers = await self.__get_auth_headers()

        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                url=endpoint,
                headers=headers,
                json=content.to_dict())

        logger.info(f'Status code: {response.status_code}')

        if response.status_code != 200:
            logger.info(f'Failed to send email: {response.text}')

        return response.json()

    async def send_datatable_email(
        self,
        recipient: str,
        subject: str,
        data: List[dict]
    ):
        logger.info(f'Sending datatable email')

        endpoint = f'{self.__base_url}/api/email/datatable'
        logger.info(f'Endpoint: {endpoint}')

        content = EmailGatewayRequest(
            recipient=recipient,
            subject=subject,
            table=data)

        headers = await self.__get_auth_headers()

        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                url=endpoint,
                headers=headers,
                json=content.to_dict())

        logger.info(f'Response status: {response.status_code}')
        return response.json()

    def get_datatable_email_request(
        self,
        recipient: str,
        subject: str,
        data: List[dict]
    ):
        endpoint = f'{self.__base_url}/api/email/datatable'
        logger.info(f'Endpoint: {endpoint}')

        content = EmailGatewayRequest(
            recipient=recipient,
            subject=subject,
            table=data)

        return content, endpoint

    def get_json_email_request(
        self,
        recipient: str,
        subject: str,
        json: Dict
    ):
        endpoint = f'{self.__base_url}/api/email/json'
        logger.info(f'Endpoint: {endpoint}')

        content = EmailGatewayRequest(
            recipient=recipient,
            subject=subject,
            json=json)

        return content, endpoint

    def get_email_request(
        self,
        recipient: str,
        subject: str,
        body: str
    ):
        endpoint = f'{self.__base_url}/api/email/send'
        logger.info(f'Endpoint: {endpoint}')

        content = EmailGatewayRequest(
            recipient=recipient,
            subject=subject,
            body=body)

        logger.info(f'Email request: {content.to_dict()}')

        return content, endpoint

    async def send_json_email(
        self,
        recipient: str,
        subject: str,
        data: Any
    ) -> Dict:
        endpoint = f'{self.__base_url}/api/email/json'
        logger.info(f'Endpoint: {endpoint}')

        content = EmailGatewayRequest(
            recipient=recipient,
            subject=subject,
            json=data)

        headers = await self.__get_auth_headers()

        async with httpx.AsyncClient(timeout=None) as client:
            response = await client.post(
                url=endpoint,
                headers=headers,
                json=content.to_dict())

        logger.info(f'Response status: {response.status_code}')
        return response.json()

    async def __get_auth_headers(
        self
    ) -> Dict[str, str]:
        logger.info(f'Fetching email gateway auth token')

        token = await self.__identity_client.get_token(
            client_name='kube-tools-api',
            scope=ClientScope.EmailGatewayApi)

        auth_headers = AuthorizationHeader(
            token=token)

        return auth_headers.to_dict()
