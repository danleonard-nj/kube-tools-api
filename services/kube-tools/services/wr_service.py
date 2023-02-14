import uuid
from datetime import datetime, timedelta

from framework.configuration import Configuration
from framework.logger import get_logger

from data.wr_repository import WellnessCheckRepository, WellnessReplyRepository
from domain.wr import WellnessCheck, WellnessReply, WellnessReplyRequest

logger = get_logger(__name__)


class WellnessCheck:
    @property
    def trigger(self):

        exceed_date = self.last_contact + timedelta(
            minutes=self.interval)

        return datetime.utcnow() > exceed_date

    def __init__(
        self,
        check_id,
        recipient,
        last_contact,
        interval
    ):
        self.check_id = check_id
        self.recipient = recipient
        self.last_contact = last_contact
        self.interval = interval

    @staticmethod
    def from_entity(
        data
    ):
        return WellnessCheck(
            check_id=data.get('check_id'),
            recipient=data.get('recipient'),
            last_contact=data.get('last_contact'),
            interval=data.get('interval'))


class WellnessResponseService:
    def __init__(
        self,
        configuration: Configuration,
        check_repository: WellnessCheckRepository
    ):
        self.__check_repository = check_repository

        self.__sender = configuration.twilio.get('wr_sender')

    async def handle_poll(
        self,
        recipient
    ):
        entity = await self.__check_repository.get({
            'recipient': recipient
        })

        check = WellnessCheck.from_entity(
            data=check)

        logger.info(f'Check found for recipient: {recipient}')

        if check.trigger:
            logger.info(f'Check triggered for : {recipient}')
