from framework.rest.blueprints.meta import MetaBlueprint

from services.gmail_service import GmailService

google_bp = MetaBlueprint('google_bp', __name__)


@google_bp.configure('/api/google/gmail', methods=['POST'], auth_scheme='default')
async def get_gmail_token(container):
    service: GmailService = container.resolve(
        GmailService)

    return await service.run_mail_service()
