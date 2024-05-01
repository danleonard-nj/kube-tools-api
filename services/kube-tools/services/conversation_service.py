import uuid

from clients.twilio_gateway import TwilioGatewayClient
from data.conversation_repository import ConversationRepository
from domain.conversation import Conversation, ConversationStatus, Direction, Message, normalize_phone_number
from framework.logger import get_logger
from pymongo.results import InsertOneResult, UpdateResult
from utilities.utils import DateTimeUtil
from twilio.request_validator import RequestValidator
from framework.configuration import Configuration
import phonenumbers

logger = get_logger(__name__)

SENDER_ID = 'placeholder-id'

TWILIO_VERIFICATION_HEADER_KEY = 'X-Twilio-Signature'


class ConversationServiceError(Exception):
    pass


class InboundRequestValidator:
    def __init__(
        self,
        configuration: Configuration
    ):
        self._auth_token = configuration.twilio.get('api_key')

    def validate(
        self,
        request_url: str,
        post_vars: dict,
        twilio_signature: str
    ):
        validator = RequestValidator(self._auth_token)

        return validator.validate(
            request_url,
            post_vars,
            twilio_signature)


class ConversationService:
    def __init__(
        self,
        configuration: Configuration,
        sms_repository: ConversationRepository,
        twilio_client: TwilioGatewayClient
    ):
        self._sms_repository = sms_repository
        self._twilio_gateway_client = twilio_client

        self._api_key = configuration.twilio.get('api_key')

    async def send_conversation_message(
        self,
        conversation_id: str,
        message: str
    ):
        logger.info(f'Fetching conversation for conversation ID: {conversation_id}')
        entity = await self._sms_repository.collection.find_one(
            filter=dict(conversation_id=conversation_id))

        if entity is None:
            logger.info(f'No conversation found for conversation ID: {conversation_id}')
            raise ConversationServiceError(f'No conversation found for conversation_id: {conversation_id}')

        conversation = Conversation.from_entity(entity)

        logger.info(f'Sending SMS to conversation recipient: {conversation.recipient}')
        result = await self._twilio_gateway_client.send_sms(
            recipient=conversation.recipient,
            message=message)

        message = Message(
            message_id=str(uuid.uuid4()),
            direction=Direction.OUTBOUND,
            content=message,
            created_date=DateTimeUtil.timestamp())

        logger.info(f'Adding message to conversation for recipient: {conversation.recipient}')
        conversation.add_message(message)

        logger.info(f'Updating conversation for recipient: {conversation.recipient}')
        update_result: UpdateResult = await self._sms_repository.collection.replace_one(
            filter=conversation.get_selector(),
            replacement=conversation.to_dict())

        return {
            'conversation': conversation,
            'twilio_result': result,
            'update_result': update_result.raw_result,
        }

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

        normalized_phone = normalize_phone_number(recipient)
        logger.info(f'Normalized phone number: {recipient} -> {normalized_phone}')

        conversation = Conversation(
            conversation_id=str(uuid.uuid4()),
            sender_id=SENDER_ID,
            recipient=normalized_phone,
            status=ConversationStatus.ACTIVE,
            messages=[message],
            created_date=DateTimeUtil.timestamp())

        logger.info(f'Creating conversation for recipient: {recipient}')

        logger.info(f'Sending SMS to recipient: {recipient}')
        result = await self._twilio_gateway_client.send_sms(
            recipient=conversation.recipient,
            message=message.content)

        logger.info(f'Inserting conversation for recipient: {recipient}')
        insert_result: InsertOneResult = await self._sms_repository.collection.insert_one(
            conversation.to_dict())

        return {
            'conversation': conversation,
            'result': result,
            'insert_result': insert_result.acknowledged,
        }

    async def get_conversation(
        self,
        conversation_id: str
    ):
        logger.info(f'Getting conversation for conversation ID: {conversation_id}')

        entity = await self._sms_repository.collection.find_one(
            filter=dict(conversation_id=conversation_id))

        if entity is None:
            logger.info(f'No conversation found for conversation ID: {conversation_id}')
            raise ConversationServiceError(f'No conversation found for conversation_id: {conversation_id}')

        conversation = Conversation.from_entity(entity)

        return conversation

    async def close_conversation(
        self,
        conversation_id: str
    ):
        logger.info(f'Closing conversation for conversation_id: {conversation_id}')

        entity = await self._sms_repository.collection.find_one(
            filter=dict(conversation_id=conversation_id))

        if entity is None:
            logger.info(f'No conversation found for conversation ID: {conversation_id}')
            raise ConversationServiceError(f'No conversation found for conversation_id: {conversation_id}')

        conversation = Conversation.from_entity(entity)

        # Set the conversation status to closed
        conversation.status = ConversationStatus.CLOSED

        logger.info(f'Closing conversation for recipient: {conversation.recipient}')

        update_result = await self._sms_repository.collection.replace_one(
            filter=conversation.get_selector(),
            replacement=conversation.to_dict())

        logger.info(f'Conversation updated: {update_result.raw_result}')

        return conversation

    async def handle_webhook(
        self,
        sender: str,
        message: str
    ):
        logger.info(f'Handling webhook for sender: {sender}')

        normalized_phone = normalize_phone_number(sender)
        logger.info(f'Normalized phone number: {sender} -> {normalized_phone}')

        # Fetch the active conversation for the sender if it exists
        query = {
            'recipient': sender,
            'status': ConversationStatus.ACTIVE
        }

        logger.info(f'Fetching active conversation for recipient: {sender}')
        entity = await self._sms_repository.collection.find_one(
            filter=query,
            sort=[('created_date', -1)])

        if entity is None:
            logger.info(f'No active conversation found for recipient: {sender}')
            raise ConversationServiceError(f'No active conversation found for recipient: {sender}')

        conversation = Conversation.from_entity(entity)
        logger.info(f'Active conversation found for recipient: {sender}: {entity}x')

        message = Message(
            message_id=str(uuid.uuid4()),
            direction=Direction.INBOUND,
            content=message,
            created_dates=DateTimeUtil.timestamp())

        logger.info(f'Adding message to active conversation for recipient: {sender}')
        conversation.add_message(message)

        logger.info(f'Updating conversation for recipient: {sender}')

        await self._sms_repository.collection.replace_one(
            filter=conversation.get_selector(),
            replacement=conversation.to_dict())

        return conversation

        # TODO: Verify an ative conversation exists
