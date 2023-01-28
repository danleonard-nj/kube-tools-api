import uuid
from datetime import datetime
from typing import Dict
from urllib.parse import unquote_plus

from framework.exceptions.nulls import ArgumentNullException
from framework.serialization import Serializable


def decode_body(message):
    return unquote_plus(message)


class WellnessReply(Serializable):
    def __init__(
        self,
        reply_id,
        sms_id,
        message_id,
        body,
        recipient,
        sender,
        service_id,
        raw_data,
        created_date
    ):
        self.reply_id = reply_id
        self.sms_id = sms_id
        self.message_id = message_id
        self.body = body
        self.recipient = recipient
        self.sender = sender
        self.service_id = service_id
        self.raw_data = raw_data
        self.created_date = created_date

    @staticmethod
    def from_respose(
        form
    ):
        quoted_body = form.get('Body')

        return WellnessReply(
            reply_id=str(uuid.uuid4()),
            sms_id=form.get('SmsMessageSid'),
            message_id=form.get('MessageSid'),
            body=decode_body(quoted_body),
            recipient=form.get('To'),
            sender=form.get('From'),
            service_id=form.get('MessagingServiceSid'),
            raw_data=form,
            created_date=datetime.now())

    @staticmethod
    def from_entity(
        data
    ):
        return WellnessReply(
            reply_id=data.get('reply_id'),
            sms_id=data.get('sms_id'),
            message_id=data.get('message_id'),
            body=data.get('body'),
            recipient=data.get('recipient'),
            sender=data.get('sender'),
            service_id=data.get('service_id'),
            raw_data=data.get('raw_data'),
            created_date=data.get('created_date')
        )


class WellnessReplyRequest:
    def __init__(
        self,
        form
    ):
        self.form = form


class WellnessCheck(Serializable):
    def __init__(
        self,
        check_id,
        name,
        threshold: int,
        recipient_type: str,
        recipient: str,
        message: str,
        frequency: str,
        switch_state: bool = True,
        failure_count: int = 0,
        last_check: datetime = None,
        modified_date: datetime = None,
        created_date: datetime = None
    ):
        self.check_id = check_id
        self.name = name
        self.threshold = threshold
        self.failure_count = failure_count
        self.recipient_type = recipient_type
        self.recipient = recipient
        self.message = message
        self.frequency = frequency
        self.last_check = last_check
        self.switch_state = switch_state
        self.modified_date = modified_date
        self.created_date = created_date

    @staticmethod
    def from_entity(data):
        return WellnessCheck(
            check_id=data.get('check_id'),
            name=data.get('name'),
            threshold=data.get('threshold'),
            failure_count=data.get('failure_count'),
            recipient=data.get('recipient'),
            recipient_type=data.get('recipient_type'),
            message=data.get('message'),
            frequency=data.get('frequency'),
            last_check=data.get('last_check'),
            switch_state=data.get('switch_state'),
            modified_date=data.get('modified_date'),
            created_date=data.get('created_date'))


class CreateWellnessCheckRequest:
    def __init__(
        self,
        body: Dict
    ):
        self.name = body.get('name')
        self.threshold = body.get('threshold')
        self.recipient = body.get('recipient')
        self.recipient_type = body.get('recipient_type')
        self.frequency = body.get('frequency')
        self.message = body.get('message')

        ArgumentNullException.if_none_or_whitespace(
            self.name, 'name')
        ArgumentNullException.if_none(
            self.threshold, 'threshold')
        ArgumentNullException.if_none_or_whitespace(
            self.recipient, 'recipient')
        ArgumentNullException.if_none_or_whitespace(
            self.recipient_type, 'recipient_type')
        ArgumentNullException.if_none_or_whitespace(
            self.frequency, 'frequency')
