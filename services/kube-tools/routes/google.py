from clients.google_auth_client import GoogleAuthClient
from domain.google import (CreateEmailRuleRequest, ProcessGmailRuleRequest,
                           UpdateEmailRuleRequest)
from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from services.gmail_rule_service import GmailRuleService
from services.gmail_service import GmailService
from services.google_auth_service import GoogleAuthService
from services.google_drive_service import GoogleDriveService
from framework.exceptions.rest import HttpException
from framework.validators.nulls import none_or_whitespace

google_bp = MetaBlueprint('google_bp', __name__)


# @google_bp.configure('/api/google/auth/v2', methods=['POST'], auth_scheme='default')
# async def get_auth_v2(container):
#     service: GoogleAuthService = container.resolve(GoogleAuthService)

#     body = await request.get_json()

#     client_name = body.get('client_name')
#     scopes = body.get('scopes', [])

#     if none_or_whitespace(client_name):
#         raise HttpException('Client name is required', 400)

#     return await service.get_token(
#         client_name=client_name,
#         scopes=scopes)


# @google_bp.configure('/api/google/auth/v3', methods=['POST'], auth_scheme='default')
# async def get_auth_v3(container):
#     service: GoogleAuthClient = container.resolve(GoogleAuthClient)

#     body = await request.get_json()

#     scopes = body.get('scopes', [])

#     return await service.get_token(
#         scopes=scopes)


@google_bp.configure('/api/google/gmail', methods=['POST'], auth_scheme='default')
async def post_gmail(container):
    service: GmailService = container.resolve(
        GmailService)

    return await service.run_mail_service()


@google_bp.configure('/api/google/gmail/rule', methods=['GET'], auth_scheme='default')
async def get_gmail_rules(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    return await service.get_rules()


@google_bp.configure('/api/google/gmail/rule/<rule_id>', methods=['GET'], auth_scheme='default')
async def get_gmail_rule(container, rule_id: str):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    if none_or_whitespace(rule_id):
        raise HttpException('Rule ID is required', 400)

    return await service.get_rule(
        rule_id=rule_id)


@google_bp.configure('/api/google/gmail/rule/process', methods=['POST'], auth_scheme='execute')
async def post_gmail_rule_process(container):
    service: GmailService = container.resolve(
        GmailService)

    body = await request.get_json()

    if body is None:
        raise HttpException('Request body is required', 400)

    process_request = ProcessGmailRuleRequest(
        data=body)

    return await service.process_rule(
        process_request=process_request)


@google_bp.configure('/api/google/gmail/rule/<rule_id>', methods=['DELETE'], auth_scheme='default')
async def delete_gmail_rule(container, rule_id: str):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    if none_or_whitespace(rule_id):
        raise HttpException('Rule ID is required', 400)

    return await service.delete_rule(
        rule_id=rule_id)


@google_bp.configure('/api/google/gmail/rule', methods=['POST'], auth_scheme='default')
async def post_gmail_rule(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    body = await request.get_json()

    if body is None:
        raise HttpException('Request body is required', 400)

    create_request = CreateEmailRuleRequest(
        data=body)

    return await service.create_rule(
        create_request=create_request)


@google_bp.configure('/api/google/gmail/rule', methods=['PUT'], auth_scheme='default')
async def put_gmail_rule(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    body = await request.get_json()

    if body is None:
        raise HttpException('Request body is required')

    update_request = UpdateEmailRuleRequest(
        data=body)

    return await service.update_rule(
        update_request=update_request)


@google_bp.configure('/api/google/drive/report', methods=['GET'], auth_scheme='default')
async def get_google_drive_report(container):
    service: GoogleDriveService = container.resolve(
        GoogleDriveService)

    return await service.get_drive_report()
