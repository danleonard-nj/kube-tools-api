from datetime import datetime
from typing import Dict, List
from flask import Config

from framework.clients.feature_client import FeatureClientAsync
from framework.concurrency import TaskCollection
from framework.exceptions.nulls import ArgumentNullException
from framework.logger import get_logger
from framework.configuration import Configuration
from clients.twilio_gateway import TwilioGatewayClient

from data.dead_man_switch_repository import DeadManSwitchRepository

DEFAULT_EXPIRATION_MINUTES = 60 * 24


def get_timestamp() -> int:
    return int(datetime.utcnow().timestamp())


logger = get_logger(__name__)


class SwitchNotFoundException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__('No dead man switch configuration is defined')


class SwitchPollResult:
    def __init__(
        self,
        seconds_remaining: int,
        is_triggered: bool
    ):
        self.seconds_remaining = seconds_remaining
        self.is_triggered = is_triggered


class Switch:
    def __init__(
        self,
        switch_id: str,
        last_disarm: int,
        last_touched: int
    ):
        self.switch_id = switch_id
        self.last_disarm = last_disarm
        self.last_touched = last_touched

    def disarm(
        self
    ):
        self.last_disarm = int(
            datetime.utcnow().timestamp())

    def get_minutes_to_expiration(
        self,
        expiration_minutes: int
    ):
        expiration = self.last_disarm + (
            expiration_minutes * 60)
        logger.info(f'Expiration: {expiration}')

        return round(
            (expiration - get_timestamp()) / 60, 2)

    @staticmethod
    def from_entity(data):
        return Switch(
            switch_id=data.get('switch_id'),
            last_disarm=data.get('last_disarm'),
            last_touched=data.get('last_touched'))


class SwitchEmergencyContact:
    def __init__(
        self,
        name: str,
        phone_number: str,
        address: str
    ):
        self.name = name
        self.phone_number = phone_number
        self.address = address

    @staticmethod
    def from_config(data):
        return SwitchEmergencyContact(
            name=data.get('name'),
            phone_number=data.get('phone_number'),
            address=data.get('address'))


class DeadManSwitchService:
    def __init__(
        self,
        configuration: Configuration,
        repository: DeadManSwitchRepository,
        twilio_gateway: TwilioGatewayClient
    ):
        self.__expiration_minutes = configuration.dms.get(
            'expiration_minutes',
            DEFAULT_EXPIRATION_MINUTES)

        self.__notification_recipients = configuration.dms.get(
            'configuration_recipients')

        contacts = configuration.dms.get('contact', [])
        self.__contacts = [
            SwitchEmergencyContact.from_config(
                data=contact
            ) for contact in contacts]

        self.__repository = repository
        self.__twilio_gateway = twilio_gateway

    async def get_switch(
        self
    ):
        entity = await self.__repository.get(dict())

        switch = Switch.from_entity(
            data=entity)

        logger.info(f'Fetched switch: {switch.switch_id}')

        if switch is None:
            logger.info(f'No switch is configured')
            raise SwitchNotFoundException()

        return switch

    async def disarm_switch(
        self
    ):
        switch = await self.get_switch()

        timestamp = int(
            datetime.utcnow().timestamp())

        logger.info(f'Disarming switch @ {timestamp}')
        switch.disarm()

    def __get_message(
        self
    ):
        message = "Activity Switch Alarm"
        message += ""
        message += f"There is a service operating a 'dead mans switch' which"
        message += f"must be disarmed at a regular cadence by the operator"
        message += f"(Dan Leonard).  If you are recieving this message then"
        message += f"the operator has not disarmed the switch in the allowed"
        message += f"timeframe (exceeding {self.__expiration_minutes} minutes)"
        message += f"which could indicate the operator is in distress.  Please"
        message += f"reach out to the operator immediately.  If the operator"
        message += f"doesn't respond, reach out to the following contacts in"
        message += f"the order presented:"
        message += ""

    async def poll(
        self
    ):
        switch = await self.get_switch()
        minutes_remaining = switch.get_minutes_to_expiration()

        if minutes_remaining > self.__expiration_minutes:
            logger.info('Switch triggered :(')

            message = self.__get_message()

            # TODO: ALert
            for recipient in self.__notification_recipients:
                logger.info(f'Sending alert to recipient: {recipient}')

                await self.__twilio_gateway.send_sms(
                    recipient=recipient,
                    message=message)
