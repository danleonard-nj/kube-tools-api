from domain.google import GoogleTokenResponse
from framework.auth.wrappers.azure_ad_wrappers import azure_ad_authorization
from framework.handlers.response_handler_async import response_handler
from quart import Blueprint, request
from services.google_auth_service import GoogleAuthService
from framework.dependency_injection.provider import inject_container_async
from utilities.meta import MetaBlueprint


google_bp = MetaBlueprint('google_bp', __name__)


@google_bp.configure('/api/google/client', methods=['GET'], auth_scheme='default')
async def get_clients(container):
    service: GoogleAuthService = container.resolve(
        GoogleAuthService)

    clients = await service.get_clients()

    return {
        'clients': clients
    }


@google_bp.configure('/api/google/client', methods=['POST'], auth_scheme='default')
async def create_client(container):
    service: GoogleAuthService = container.resolve(
        GoogleAuthService)

    data = await request.get_json()

    client = await service.create_client(
        data=data)

    return client


@google_bp.configure('/api/google/client/<client_id>', methods=['GET'], auth_scheme='default')
async def get_client(container, client_id):
    service: GoogleAuthService = container.resolve(
        GoogleAuthService)

    client = await service.get_client(
        client_id=client_id)

    return client


@google_bp.configure('/api/google/client/<client_id>/token', methods=['GET'], auth_scheme='default')
async def get_client_token(container, client_id):
    service: GoogleAuthService = container.resolve(
        GoogleAuthService)

    creds = await service.get_credentials(
        client_id=client_id)

    response = GoogleTokenResponse(
        creds=creds)

    return response


@google_bp.configure('/api/google/client/refresh', methods=['POST'], auth_scheme='default')
async def refresh_client_token(container):
    service: GoogleAuthService = container.resolve(
        GoogleAuthService)

    clients = await service.refresh_clients()

    return {
        'clients': clients
    }
