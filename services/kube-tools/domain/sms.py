from datetime import datetime
from typing import Dict, List
from framework.serialization import Serializable


class SmsApplicationId:
    WellnessResponseService = 'wellness-response'


class SmsThreadDirection:
    Inbound = 'inbound'
    Outbound = 'outbound'


class SmsConversationThread(Serializable):
    def __init__(
        self,
        direction: str,
        message: str,
        timestamp: int,
        data: Dict = None
    ):
        self.direction = direction
        self.message = message
        self.timestamp = timestamp
        self.data = data

    @staticmethod
    def from_entity(data):
        return SmsConversationThread(
            direction=data.get('direction'),
            message=data.get('message'),
            data=data.get('data'),
            timestamp=data.get('timestamp'))


class SmsConversation(Serializable):
    def __init__(
        self,
        conversation_id: str,
        application_id: str,
        sender: str,
        recipient: str,
        thread: List[SmsConversationThread],
        initial_direction: str,
        created_date: datetime,
        closed_date: datetime = None,
        is_closed: bool = None,
        modified_date: datetime = None
    ):

        self.conversation_id = conversation_id
        self.application_id = application_id
        self.initial_direction = initial_direction
        self.sender = sender
        self.recipient = recipient
        self.thread = thread
        self.created_date = created_date
        self.modified_date = modified_date
        self.is_closed = is_closed
        self.closed_date = closed_date

    @staticmethod
    def from_entity(data):
        threads = [SmsConversationThread.from_entity(data=thread)
                   for thread in data.get('thread')]

        return SmsConversation(
            conversation_id=data.get('conversation_id'),
            application_id=data.get('application_id'),
            sender=data.get('sender'),
            thread=threads,
            initial_direction=data.get('initial_directions'),
            recipient=data.get('recipient'),
            created_date=data.get('created_date'),
            modified_date=data.get('modified_date'),
            is_closed=data.get('is_closed'),
            closed_date=data.get('closed_date'))

    def to_dict(self) -> Dict:
        return super().to_dict() | {
            'thread': [
                thr.to_dict()
                for thr in self.thread
            ]
        }
