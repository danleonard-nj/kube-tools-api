from framework.rest.blueprints.meta import MetaBlueprint

from clients.gmail_client import GmailClient

google_bp = MetaBlueprint('google_bp', __name__)


@google_bp.configure('/api/google/gmail', methods=['POST'], auth_scheme='default')
async def get_gmail_token(container):
    service: GmailClient = container.resolve(
        GmailClient)

    return await service.run_mail_service()


@google_bp.configure('/api/google/gmail/<message_id>', methods=['GET'], auth_scheme='default')
async def get_email(container, message_id):
    service: GmailClient = container.resolve(
        GmailClient)

    result = await service.get_message(
        message_id=message_id)

    return result
