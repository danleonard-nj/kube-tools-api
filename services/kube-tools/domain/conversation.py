import enum
from typing import Dict
from framework.serialization import Serializable
import phonenumbers

from utilities.utils import DateTimeUtil


def normalize_phone_number(
    phone_number: str
) -> str:
    '''
    Normalize phone number to E.164 format
    '''

    parsed_number = phonenumbers.parse(
        number=phone_number,
        region='US')

    return phonenumbers.format_number(
        parsed_number,
        phonenumbers.PhoneNumberFormat.E164)


class ConversationStatus(enum.StrEnum):
    ACTIVE = 'active'
    CLOSED = 'closed'


class Direction:
    INBOUND = 'inbound'
    OUTBOUND = 'outbound'


class Message(Serializable):
    def __init__(
        self,
        message_id: str,
        direction: str,
        content: str,
        created_date
    ):
        self.message_id = message_id
        self.direction = direction
        self.content = content
        self.created_date = created_date

    @staticmethod
    def from_entity(
        data: dict
    ):
        return Message(
            message_id=data.get('message_id'),
            direction=data.get('direction'),
            content=data.get('content'),
            created_date=data.get('created_date'))


class Conversation(Serializable):
    def __init__(
        self,
        conversation_id: str,
        sender_id,
        recipient: str,
        status: ConversationStatus,
        service_type: str,
        messages: list[Message],
        created_date,
        modified_date=0
    ):
        self.conversation_id = conversation_id
        self.sender_id = sender_id
        self.recipient = recipient
        self.status = status
        self.service_type = service_type
        self.messages = messages
        self.created_date = created_date
        self.modified_date = modified_date

    def add_message(
        self,
        message: Message
    ):
        self.messages.append(message)
        self.modified_date = DateTimeUtil.timestamp()

    def to_dict(self) -> Dict:
        return super().to_dict() | {
            'messages': [
                message.to_dict()
                for message in self.messages
            ]
        }

    def get_selector(
        self
    ):
        return {
            'conversation_id': self.conversation_id
        }

    @staticmethod
    def from_entity(
        data: dict
    ):
        messages = [Message.from_entity(message)
                    for message in data.get('messages', [])]

        status = ConversationStatus(data.get('status'))

        return Conversation(
            conversation_id=data.get('conversation_id'),
            sender_id=data.get('sender_id'),
            recipient=data.get('recipient'),
            service_type=data.get('service_type'),
            status=status,
            messages=messages,
            created_date=data.get('created_date'),
            modified_date=data.get('modified_date'))
