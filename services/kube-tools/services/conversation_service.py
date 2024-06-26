import uuid

from clients.twilio_gateway import TwilioGatewayClient
from data.conversation_repository import ConversationRepository
from domain.conversation import (Conversation, ConversationStatus, Direction,
                                 Message, normalize_phone_number)
from domain.features import Feature
from framework.clients.feature_client import FeatureClientAsync
from framework.configuration import Configuration
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from pymongo.results import InsertOneResult, UpdateResult
from utilities.utils import DateTimeUtil

logger = get_logger(__name__)


class ConversationServiceError(Exception):
    pass


class ConversationService:
    def __init__(
        self,
        configuration: Configuration,
        sms_repository: ConversationRepository,
        twilio_client: TwilioGatewayClient,
        feature_client: FeatureClientAsync
    ):
        self._sms_repository = sms_repository
        self._twilio_gateway_client = twilio_client
        self._feature_client = feature_client

        self._api_key = configuration.twilio.get('api_key')

    async def send_conversation_message(
        self,
        conversation_id: str,
        message: str
    ):
        ArgumentNullException.if_none_or_whitespace(conversation_id, 'conversation_id')
        ArgumentNullException.if_none_or_whitespace(message, 'message')

        logger.info(f'Fetching conversation for conversation ID: {conversation_id}')
        entity = await self._sms_repository.get_conversation_by_id(
            conversation_id=conversation_id)

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
        update_result: UpdateResult = await self._sms_repository.replace(
            selector=conversation.get_selector(),
            document=conversation.to_dict())

        return conversation

    async def create_conversation(
        self,
        recipient,
        message: str,
        service_type: str = None
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
            sender_id='placeholder-id',
            recipient=normalized_phone,
            status=ConversationStatus.ACTIVE,
            service_type=service_type,
            messages=[message],
            created_date=DateTimeUtil.timestamp())

        logger.info(f'Creating conversation for recipient: {recipient}')

        logger.info(f'Sending SMS to recipient: {recipient}')
        result = await self._twilio_gateway_client.send_sms(
            recipient=conversation.recipient,
            message=message.content)

        logger.info(f'Inserting conversation for recipient: {recipient}')
        insert_result: InsertOneResult = await self._sms_repository.insert(
            document=conversation.to_dict())

        logger.info(f'Conversation inserted: {insert_result.inserted_id}')

        return conversation

    async def get_conversation(
        self,
        conversation_id: str
    ):
        logger.info(f'Getting conversation for conversation ID: {conversation_id}')

        entity = await self._sms_repository.get_conversation_by_id(
            conversation_id=conversation_id)

        if entity is None:
            logger.info(f'No conversation found for conversation ID: {conversation_id}')
            raise ConversationServiceError(f'No conversation found for conversation_id: {conversation_id}')

        conversation = Conversation.from_entity(entity)

        return conversation

    async def get_conversations(
        self
    ):
        logger.info(f'Getting all conversations')

        entities = await self._sms_repository.get_all()

        conversations = [Conversation.from_entity(entity)
                         for entity in entities]

        return conversations

    async def close_conversation(
        self,
        conversation_id: str
    ):
        logger.info(f'Closing conversation for conversation_id: {conversation_id}')

        entity = await self._sms_repository.get_conversation_by_id(
            conversation_id=conversation_id)

        if entity is None:
            logger.info(f'No conversation found for conversation ID: {conversation_id}')
            raise ConversationServiceError(f'No conversation found for conversation_id: {conversation_id}')

        conversation = Conversation.from_entity(entity)

        # Set the conversation status to closed
        conversation.status = ConversationStatus.CLOSED

        logger.info(f'Closing conversation for recipient: {conversation.recipient}')

        update_result = await self._sms_repository.replace(
            selector=conversation.get_selector(),
            document=conversation.to_dict())

        logger.info(f'Conversation updated: {update_result.raw_result}')

        return conversation

    async def handle_webhook(
        self,
        sender: str,
        message: str
    ):
        logger.info(f'Handling webhook for sender: {sender}')

        inbound_no_trigger_word_logging_enabled = await self._feature_client.is_enabled(
            feature_key=Feature.ConversationServiceInboundNoTriggerWord)

        logger.info(f'Inbound no trigger word logging enabled: {inbound_no_trigger_word_logging_enabled}')

        # Parse and normalize the phone number formatting
        normalized_phone = normalize_phone_number(
            phone_number=sender)

        logger.info(f'Normalized phone number: {sender} -> {normalized_phone}')

        logger.info(f'Fetching active conversation for recipient: {sender}')
        entity = await self._sms_repository.get_conversation_by_recipient_status(
            recipient=normalized_phone,
            status=ConversationStatus.ACTIVE)

        # No active conversation exists for the sender
        if entity is None:
            logger.info(f'No active conversation found for sender: {sender}')

            # TODO: Create new conversation if trigger word is found in inbound message
            if message.lower().strip() == 'gizmo':
                logger.info(f'Creating new conversation for sender: {sender}')

                # TODO: Create new conversation on trigger word
                # await self.create_conversation(
                #     recipient=sender,
                #     message='intro-message')
            else:
                # Log if no trigger word is found in inbound message
                if inbound_no_trigger_word_logging_enabled:
                    logger.info(f'No trigger word found in inbound message')

                raise ConversationServiceError(f'No active conversation found for sender: {sender}')

        conversation = Conversation.from_entity(entity)
        logger.info(f'Active conversation found for recipient: {sender}: {entity}')

        message = Message(
            message_id=str(uuid.uuid4()),
            direction=Direction.INBOUND,
            content=message,
            created_date=DateTimeUtil.timestamp())

        logger.info(f'Adding message to active conversation for recipient: {sender}')
        conversation.add_message(message)

        logger.info(f'Updating conversation for recipient: {sender}')

        await self._sms_repository.replace(
            selector=conversation.get_selector(),
            document=conversation.to_dict())

        return conversation

        # TODO: Verify an ative conversation exists
