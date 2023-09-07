from datetime import datetime, timedelta

from framework.configuration import Configuration
from framework.logger import get_logger
from clients.email_gateway_client import EmailGatewayClient

from clients.twilio_gateway import TwilioGatewayClient
from data.dead_man_switch_repository import DeadManSwitchRepository
from domain.dms import (DEFAULT_EXPIRATION_MINUTES, Switch,
                        SwitchNotFoundException)
from domain.rest import DeadManSwitchPollDisabledResponse, DeadManSwitchPollResponse
from utilities.utils import DateTimeUtil

RECIPIENT_PHONE_NUMBER = '+18563323608'
RECIPIENT_EMAIL = 'dcl525@gmail.com'

REMINDER_ONE_HOUR = 60
REMINDER_TWELVE_HOURS = 720
REMINDER_ONE_DAY_MINUTES = 1440


logger = get_logger(__name__)


class DeadManSwitchService:
    def __init__(
        self,
        configuration: Configuration,
        repository: DeadManSwitchRepository,
        twilio_gateway: TwilioGatewayClient,
        email_gateway: EmailGatewayClient
    ):
        self.__twilio_gateway = twilio_gateway
        self.__email_gateway = email_gateway
        self.__repository = repository

        self.__expiration_minutes = configuration.dms.get(
            'expiration_minutes',
            DEFAULT_EXPIRATION_MINUTES)

    async def disarm_switch(
        self
    ):
        logger.info(f'Disarming switch')
        switch = await self.__get_switch()

        switch = await self.__ensure_switch(
            switch=switch,
            enable_switch=True)

        switch.last_disarm = DateTimeUtil.timestamp()

        update = await self.__repository.replace(
            selector=switch.get_selector(),
            document=switch.to_dict())

        logger.info(f'Update result: {update.modified_count}')

        return switch

    async def poll(
        self,
        enable_switch: bool = False
    ):
        notified = False

        switch = await self.__get_switch()

        if not switch.is_enabled and not enable_switch:
            logger.info(f'Switch is disabled')
            return DeadManSwitchPollDisabledResponse()

        switch = await self.__ensure_switch(
            switch=switch,
            enable_switch=enable_switch)

        seconds_remaining = switch.get_seconds_remaining()
        minutes_remaining = seconds_remaining / 60

        expiration_date = datetime.fromtimestamp(switch.expiration)
        logger.info(f'Expiration: {expiration_date.isoformat()}')

        if seconds_remaining < 0:
            logger.info('Switch triggered - notifying emergency contact')

            await self.__notify_recipient()
            notified = True

            # Disable the switch, one and done
            switch.last_disarm = DateTimeUtil.timestamp()
            switch.is_enabled = False

        else:
            logger.info(f'Switch not triggered - handling reminders')
            switch = await self.__handle_reminders(switch)

        logger.info(f'Updating switch document: {switch.switch_id}')

        switch.last_touched = DateTimeUtil.timestamp()

        update_result = await self.__repository.replace(
            selector=switch.get_selector(),
            document=switch.to_dict())

        logger.info(f'Update result: {update_result.modified_count}')

        return DeadManSwitchPollResponse(
            seconds_remaining=seconds_remaining,
            minutes_remaining=minutes_remaining,
            notified=notified,
            expiration_date=expiration_date,
            switch=switch)

    async def send_reminder(
        self,
        switch: Switch,
        interval: str
    ):
        subject = f'Disarm Reminder: {interval}'

        await self.__email_gateway.send_json_email(
            recipient=RECIPIENT_EMAIL,
            subject=subject,
            data=switch.to_dict())

    async def __handle_reminders(
        self,
        switch: Switch
    ):
        minutes_remaining = switch.expiration_minutes

        if (minutes_remaining < REMINDER_ONE_DAY_MINUTES
            and minutes_remaining > REMINDER_TWELVE_HOURS
                and switch.last_notification != 'REMINDER_ONE_DAY'):
            logger.info(f'Sending reminder one day notification')

            await self.send_reminder(
                switch=switch,
                interval='24 Hours')

            switch.last_notification = 'REMINDER_ONE_DAY'

        elif (minutes_remaining < REMINDER_TWELVE_HOURS
                and minutes_remaining > REMINDER_ONE_HOUR
                and switch.last_notification != 'REMINDER_TWELVE_HOURS'):
            logger.info(f'Sending reminder twelve hour notification')

            await self.send_reminder(
                switch=switch,
                interval='12 Hours')

            switch.last_notification = 'REMINDER_TWELVE_HOURS'

        elif (minutes_remaining < REMINDER_ONE_HOUR
                and switch.last_notification != 'REMINDER_ONE_HOUR'):
            logger.info(f'Sending reminder one hour notification')

            await self.send_reminder(
                switch=switch,
                interval='1 Hour')

            switch.last_notification = 'REMINDER_ONE_HOUR'

        return switch

    async def __get_switch(
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

    async def __notify_recipient(
        self
    ):
        logger.info(f'Notifying emergency contact for elapsed switch')

        await self.__twilio_gateway.send_sms(
            recipient=RECIPIENT_PHONE_NUMBER,
            message=self.__get_first_message())

    async def __ensure_switch(
        self,
        switch: Switch,
        enable_switch: bool
    ):
        if enable_switch:
            logger.info(f'Enabling switch')
            switch.is_enabled = True

        if switch.expiration_minutes != self.__expiration_minutes:
            logger.info(
                f'Updating expiration minutes: {switch.expiration_minutes} -> {self.__expiration_minutes}')

            switch.expiration_minutes = self.__expiration_minutes

        if (switch.last_disarm is None
                or switch.last_disarm == 0):

            logger.info(
                f'Setting initial log disarm time: {switch.last_disarm}')

            switch.last_disarm = DateTimeUtil.timestamp()

        if (switch.last_touched is None
                or switch.last_touched == 0):

            logger.info(
                f'Setting initial log touch time: {switch.last_touched}')

            switch.last_touched = DateTimeUtil.timestamp()

        return switch

    def __get_first_message(
        self
    ):
        timeframe = timedelta(minutes=self.__expiration_minutes)

        message = "Activity Switch Alarm - Dan Leonard \n"
        message += "\n"
        message += f"This is your first alert notifying you that an "
        message += f"activity switch has been triggered.  The switch "
        message += f"a safety mechanism that notifies a recipient if "
        message += f"the switch operator hasn't disarmed the switch within "
        message += f"the allowed timeframe (current timeframe configuration {timeframe}). "
        message += f"If you're recieving this message then it might be a good "
        message += f"time to check in on the switch operator."
        message += '\n\n'
        message += f'A follow up alert will be triggered if the switch is not '
        message += f'disarmed within an additional 24 hour timeframe'
        message += f'\n\n'
        message += f"Regards, Kube-Tools DMS API"

        return message
