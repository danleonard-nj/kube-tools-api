from framework.exceptions.nulls import ArgumentNullException
from framework.rest.blueprints.meta import MetaBlueprint
from quart import Response, request

from domain.rest import (CreateEmailRuleRequest, ProcessGmailRuleRequest,
                         UpdateEmailRuleRequest)
from services.gmail_rule_service import GmailRuleService
from services.gmail_service import GmailService
from services.google_auth_service import GoogleAuthService

google_bp = MetaBlueprint('google_bp', __name__)


@google_bp.configure('/api/google/auth', methods=['POST'], auth_scheme='default')
async def get_auth(container):
    service: GoogleAuthService = container.resolve(
        GoogleAuthService)

    body = await request.get_json()
    scopes = body.get('scopes', [])

    client = await service.get_auth_client(
        scopes=scopes)

    return Response(
        response=client.to_json(),
        content_type='application/json'
    )


@ google_bp.configure('/api/google/gmail', methods=['POST'], auth_scheme='default')
async def post_gmail(container):
    service: GmailService = container.resolve(
        GmailService)

    return await service.run_mail_service()


@ google_bp.configure('/api/google/gmail/rule', methods=['GET'], auth_scheme='default')
async def get_gmail_rules(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    return await service.get_rules()


@ google_bp.configure('/api/google/gmail/rule/<rule_id>', methods=['GET'], auth_scheme='default')
async def get_gmail_rule(container, rule_id: str):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    ArgumentNullException.if_none_or_whitespace(
        rule_id, 'rule_id')

    return await service.get_rule(
        rule_id=rule_id)


@ google_bp.configure('/api/google/gmail/rule/process', methods=['POST'], auth_scheme='execute')
async def post_gmail_rule_process(container):
    service: GmailService = container.resolve(
        GmailService)

    body = await request.get_json()

    ArgumentNullException.if_none_or_whitespace(
        body, 'body')

    process_request = ProcessGmailRuleRequest(
        data=body)

    return await service.process_rule(
        process_request=process_request)


@ google_bp.configure('/api/google/gmail/rule/<rule_id>', methods=['DELETE'], auth_scheme='default')
async def delete_gmail_rule(container, rule_id: str):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    ArgumentNullException.if_none_or_whitespace(
        rule_id, 'rule_id')

    return await service.delete_rule(
        rule_id=rule_id)


@ google_bp.configure('/api/google/gmail/rule', methods=['POST'], auth_scheme='default')
async def post_gmail_rule(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    body = await request.get_json()

    create_request = CreateEmailRuleRequest(
        data=body)

    return await service.create_rule(
        create_request=create_request)


@ google_bp.configure('/api/google/gmail/rule', methods=['PUT'], auth_scheme='default')
async def put_gmail_rule(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    body = await request.get_json()

    update_request = UpdateEmailRuleRequest(
        data=body)

    return await service.update_rule(
        update_request=update_request)
