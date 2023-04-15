import uuid
from datetime import datetime
from typing import Dict

from framework.exceptions.nulls import ArgumentNullException
from framework.serialization import Serializable
from framework.validators.nulls import none_or_whitespace

from domain.exceptions import InvalidAlertTypeException


class AlertType:
    Email = 'email'
    SMS = 'sms'

    @classmethod
    def verify_is_valid_alert_type(
        cls,
        alert_type: str
    ):
        ''' Validate provided alert type is known'''

        ArgumentNullException.if_none_or_whitespace(alert_type, 'alert_type')

        if alert_type not in [cls.Email,
                              cls.SMS]:
            raise InvalidAlertTypeException(
                alert_type=alert_type)


class DeadManSwitch(Serializable):
    def __init__(
        self,
        switch_id: str,
        switch_name: str,
        configuration_id: str,
        created_date: datetime,
        is_active: bool = True,
        last_message: datetime = None,
        last_disarm: datetime = None,
        modified_date: datetime = None,
        configuration: datetime = None
    ):
        self.switch_id = switch_id
        self.switch_name = switch_name
        self.configuration_id = configuration_id
        self.last_message = last_message
        self.last_disarm = last_disarm
        self.is_active = is_active
        self.created_date = created_date
        self.modified_date = modified_date
        self.configuration = None

    def get_selector(
        self
    ):
        return {
            'switch_id': self.switch_id
        }

    @staticmethod
    def from_entity(
        data: Dict
    ):
        return DeadManSwitch(
            switch_id=data.get('switch_id'),
            switch_name=data.get('switch_name'),
            configuration_id=data.get('configuration_id'),
            last_message=data.get('last_message'),
            last_disarm=data.get('last_disarm'),
            is_active=data.get('is_active'),
            created_date=data.get('created_date'),
            modified_date=data.get('modified_date'))

    @staticmethod
    def create_dead_mans_switch(
        configuration_id: str,
        switch_name: str
    ):
        ArgumentNullException.if_none_or_whitespace(
            configuration_id,
            'configuration_id')
        ArgumentNullException.if_none_or_whitespace(
            switch_name,
            'switch_name')

        return DeadManSwitch(
            switch_id=str(uuid.uuid4()),
            switch_name=switch_name,
            configuration_id=configuration_id,
            created_date=datetime.utcnow())


class DeadManSwitchConfiguration(Serializable):
    def __init__(
        self,
        configuration_id: str,
        configuration_name: str,
        interval_hours: int,
        grace_period_hours: int,
        alert_type: str,
        alert_address: str,
        created_date: datetime,
        modified_date: datetime = None,
        switches=None
    ):
        self.configuration_id = configuration_id
        self.configuration_name = configuration_name
        self.interval_hours = interval_hours
        self.grace_period_hours = grace_period_hours
        self.alert_type = alert_type
        self.alert_address = alert_address
        self.created_date = created_date
        self.modified_date = modified_date
        self.switches = switches

    @staticmethod
    def create_configuration(
        configuration_name: str,
        interval_hours: int,
        grace_period_hours: int,
        alert_type: str,
        alert_address: str
    ) -> 'DeadManSwitchConfiguration':

        ArgumentNullException.if_none_or_whitespace(
            configuration_name, 'configuration_name')
        ArgumentNullException.if_none_or_whitespace(
            configuration_name, 'alert_type')
        ArgumentNullException.if_none_or_whitespace(
            alert_address, 'alert_address')
        ArgumentNullException.if_none(
            interval_hours, 'interval_hours')
        ArgumentNullException.if_none(
            grace_period_hours, 'grace_period_hours')

        # Validate the alert type
        AlertType.verify_is_valid_alert_type(
            alert_type=alert_type)

        return DeadManSwitchConfiguration(
            configuration_id=str(uuid.uuid4()),
            configuration_name=configuration_name,
            interval_hours=interval_hours,
            grace_period_hours=grace_period_hours,
            alert_type=alert_type,
            alert_address=alert_address,
            created_date=datetime.utcnow())

    @staticmethod
    def from_entity(
        data: Dict
    ) -> 'DeadManSwitchConfiguration':

        ArgumentNullException.if_none(data, 'data')

        return DeadManSwitchConfiguration(
            configuration_id=data.get('configuration_id'),
            configuration_name=data.get('configuration_name'),
            interval_hours=data.get('interval_hours'),
            grace_period_hours=data.get('grace_period_hours'),
            alert_type=data.get('alert_type'),
            alert_address=data.get('alert_address'),
            created_date=data.get('created_date'),
            modified_date=data.get('modified_date'))

    def update_configuration(
        self,
        configuration_name: str,
        interval_hours: int,
        grace_period_hours: int,
        alert_type: str,
        alert_address: str
    ):
        ArgumentNullException.if_none_or_whitespace(
            configuration_name, 'configuration_name')

        if configuration_name != self.configuration_name:
            self.configuration_name = configuration_name

        if (interval_hours is not None
                and interval_hours != self.interval_hours):
            self.interval_hours = interval_hours

        if (grace_period_hours is not None
                and grace_period_hours != self.grace_period_hours):
            self.grace_period_hours = grace_period_hours

        # Validate the alert type before updating
        if (not none_or_whitespace(alert_type)
                and alert_type != self.alert_type):
            AlertType.verify_is_valid_alert_type(
                alert_type=alert_type)

            self.alert_type = alert_type

        if (not none_or_whitespace(alert_address)
                and alert_address != self.alert_address):
            self.alert_address = alert_address

    def get_selector(
        self
    ) -> Dict:

        return {
            'configuration_id': self.configuration_id
        }
