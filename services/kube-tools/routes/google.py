from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from domain.google import CreateEmailRuleRequestModel, ProcessGmailRuleRequest, UpdateEmailRuleRequestModel
from services.gmail_rule_service import GmailRuleService
from services.gmail_service import GmailService
from services.google_auth_service import GoogleAuthService
from services.google_drive_service import GoogleDriveService
from framework.exceptions.rest import HttpException
from framework.validators.nulls import none_or_whitespace

google_bp = MetaBlueprint('google_bp', __name__)


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

    create_request = CreateEmailRuleRequestModel.from_dict(data=body)

    return await service.create_rule(
        create_request=create_request)


@google_bp.configure('/api/google/gmail/rule', methods=['PUT'], auth_scheme='default')
async def put_gmail_rule(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    body = await request.get_json()

    if body is None:
        raise HttpException('Request body is required')

    update_request = UpdateEmailRuleRequestModel(data=body)

    return await service.update_rule(
        update_request=update_request)


@google_bp.configure('/api/google/drive/report', methods=['GET'], auth_scheme='default')
async def get_google_drive_report(container):
    service: GoogleDriveService = container.resolve(
        GoogleDriveService)

    return await service.get_drive_report()


@google_bp.configure('/api/google/save_client', methods=['POST'], auth_scheme='default')
async def save_client(container):
    service: GoogleAuthService = container.resolve(GoogleAuthService)
    body = await request.get_json()
    client_name = body.get('client_name')
    client_id = body.get('client_id')
    client_secret = body.get('client_secret')
    refresh_token = body.get('refresh_token')

    if none_or_whitespace(client_name):
        raise HttpException('client_name is required', 400)
    if none_or_whitespace(client_id):
        raise HttpException('client_id is required', 400)
    if none_or_whitespace(client_secret):
        raise HttpException('client_secret is required', 400)
    if none_or_whitespace(refresh_token):
        raise HttpException('refresh_token is required', 400)

    await service.save_client(
        client_name=client_name,
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token
    )
    return {"success": True, "message": f"Client '{client_name}' saved with fresh token."}


@google_bp.configure('/api/google/get_token', methods=['POST'], auth_scheme='default')
async def get_token_endpoint(container):
    service: GoogleAuthService = container.resolve(GoogleAuthService)
    body = await request.get_json()
    client_name = body.get('client_name')
    scopes = body.get('scopes')

    if none_or_whitespace(client_name):
        raise HttpException('client_name is required', 400)
    if not scopes or not isinstance(scopes, list):
        raise HttpException('scopes must be a non-empty list', 400)

    token = await service.get_token(client_name=client_name, scopes=scopes)
    return {"token": token}
