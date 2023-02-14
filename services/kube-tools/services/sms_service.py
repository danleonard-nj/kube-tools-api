import json
import uuid
from datetime import datetime
from typing import Any

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from framework.configuration.configuration import Configuration
from framework.logger.providers import get_logger

from data.sms_repository import SmsRepository
from domain.sms import (SmsConversation, SmsConversationThread,
                        SmsThreadDirection)

logger = get_logger(__name__)

service_numbers = [
    '+12183221586'
]


class SmsService:
    def __init__(
        self,
        configuration: Configuration,
        repository: SmsRepository
    ):
        connecion_string = configuration.service_bus.get(
            'connection_string')

        self.__client = ServiceBusClient.from_connection_string(
            conn_str=connecion_string)

        self.__sender = self.__client.get_queue_sender(
            queue_name='sms-twilio')

        self.__repository = repository

    def handle_message(
        self,
        message
    ):
        logger.info('Handling event message')
        service_bus_message = ServiceBusMessage(
            body=json.dumps(message))

        logger.info(f'Message: {service_bus_message}')

        self.__sender.send_messages(
            message=service_bus_message)
        logger.info(f'Message sent successfully')

    def get_conversation(
        self,
        sender: str,
        recipient: str
    ):
        active_convo = self.__repository.get({
            'sender': sender,
            'recipient': recipient,
            'is_closed': False
        })

        if active_convo is not None:
            return SmsConversation.from_entity(
                data=active_convo)

    async def create_conversation(
        self,
        sender: str,
        recipient: str,
        application_id: str
    ):
        convo_id = str(uuid.uuid4())
        logger.info(f'Creating new conversation: {convo_id}')

        existing = await self.__repository.query({
            'sender': sender,
            'recipient': recipient,
            'application_id': application_id
        })

        if existing:
            raise Exception(f"An active conversation exists")

        logger.info(f'Sender: {sender}')
        logger.info(f'Recipient: {recipient}')

        # Get the origin direction (inbound if
        # initial sender is a service number)

        initial_direction = (
            SmsThreadDirection.Outbound
            if sender in service_numbers
            else SmsThreadDirection.Inbound
        )

        logger.info(f'Initial direction: {initial_direction}')

        # Create new conversation

        conversation = SmsConversation(
            conversation_id=convo_id,
            application_id=application_id,
            sender=sender,
            recipient=recipient,
            thread=list(),
            initial_direction=initial_direction,
            created_date=datetime.utcnow())

        logger.info(f'Created convo: {conversation.to_dict()}')

        await self.__repository.insert(
            document=conversation.to_dict()
        )

        return conversation

    async def reply_conversation(
        self,
        conversation_id: str,
        message: Any
    ):
        logger.info(f'Reply conversation: {conversation_id}')
        convo_entity = await self.__repository.get({
            'conversation_id': conversation_id
        })

        if convo_entity is None:
            raise Exception(
                f"No conversation with the ID '{conversation_id}' exists")

        convo = SmsConversation.from_entity(
            data=convo_entity)

        timestamp = datetime.utcnow()

        thread = SmsConversationThread(
            direction=SmsThreadDirection.Outbound,
            message=message,
            timestamp=timestamp)

        convo.thread.append(thread)
        logger.info(f'Added thread to conversation')

        await self.__repository.replace(
            selector={'conversation_id': conversation_id},
            document=convo.to_dict())

        return convo

    async def get_conversations(
        self
    ):
        entities = await self.__repository.get_all()

        convos = [SmsConversation.from_entity(
            data=entity).to_dict()
            for entity in entities]

        return convos

    async def lookup_active_conversation(
        self,
        sender,
        recipient
    ):
        entities = await self.__repository.query({
            'sender': sender,
            'recipient': recipient,
            'is_closed': True
        })

        convos = [
            SmsConversation.from_entity(
                data=entity)
            for entity in entities
        ]

        return convos

    async def handle_inbound(
        self
    ):
        pass
