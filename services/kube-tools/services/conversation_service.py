import uuid

from clients.twilio_gateway import TwilioGatewayClient
from data.conversation_repository import ConversationRepository
from domain.sms import Conversation, ConversationStatus, Direction, Message
from framework.logger import get_logger
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)

SENDER_ID = 'placeholder-id'


class ConversationServiceError(Exception):
    pass


class ConversationService:
    def __init__(
        self,
        sms_repository: ConversationRepository,
        twilio_client: TwilioGatewayClient
    ):
        self._sms_repository = sms_repository
        self._twilio_gateway_client = twilio_client

    async def create_conversation(
        self,
        recipient,
        message: str
    ):
        # TODO: Verify an active conversation does not already exist

        message = Message(
            message_id=str(uuid.uuid4()),
            direction=Direction.OUTBOUND,
            content=message,
            created_date=DateTimeUtil.timestamp())

        conversation = Conversation(
            conversation_id=str(uuid.uuid4()),
            sender_id=SENDER_ID,
            recipient=recipient,
            status=ConversationStatus.ACTIVE,
            messages=[message],
            created_date=DateTimeUtil.timestamp())

        logger.info(f'Creating conversation for recipient: {recipient}')

        await self._sms_repository.collection.insert_one(
            conversation.to_dict())

        logger.info(f'Sending SMS to recipient: {recipient}')
        result = await self._twilio_gateway_client.send_sms(
            recipient=recipient,
            message=message.content)

        return {
            'conversation': conversation.to_dict(),
            'result': result
        }

    async def handle_webhook(
        self,
        sender: str,
        message: str
    ):
        logger.info(f'Handling webhook for sender: {sender}')

        # Fetch the active conversation for the sender if it exists
        query = {
            'recipient': sender,
            'status': ConversationStatus.ACTIVE
        }

        entity = await self._sms_repository.collection.find_one(
            filter=query,
            sort=[('created_date', -1)])

        if entity is None:
            raise ConversationServiceError(f'No active conversation found for recipient: {sender}')

        logger.info(f'Message: {message}')

        message = Message(
            message_id=str(uuid.uuid4()),
            direction=Direction.INBOUND,
            content=message,
            created_date=DateTimeUtil.timestamp())

        logger.info(f'Adding message to conversation for recipient: {sender}')
        conversation = Conversation.from_entity(entity)

        conversation.add_message(message)

        query = {
            'conversation_id': conversation.conversation_id,
        }

        logger.info(f'Updating conversation for recipient: {sender}')

        await self._sms_repository.collection.replace_one(
            filter=dict(conversation_id=conversation.conversation_id),
            replacement=conversation.to_dict())

        return conversation

        # TODO: Verify an ative conversation exists
