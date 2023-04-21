from framework.rest.blueprints.meta import MetaBlueprint
from quart import request
from domain.rest import CreateEmailRuleRequest

from services.gmail_rule_service import GmailRuleService
from services.gmail_service import GmailService

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


@google_bp.configure('/api/google/gmail/rule', methods=['POST'], auth_scheme='default')
async def post_gmail_rule(container):
    service: GmailRuleService = container.resolve(
        GmailRuleService)

    body = await request.get_json()

    create_request = CreateEmailRuleRequest(
        data=body)

    return await service.create_rule(
        create_request=create_request)
