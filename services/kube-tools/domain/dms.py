from datetime import datetime, timedelta
import time
from typing import Dict
from framework.serialization import Serializable

from utilities.utils import DateTimeUtil

DEFAULT_EXPIRATION_MINUTES = 60 * 24


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


class Switch(Serializable):
    @property
    def expiration(
        self
    ):
        result = (
            datetime.fromtimestamp(self.last_disarm) +
            timedelta(minutes=self.expiration_minutes)
        )

        return int(result.timestamp())

    def __init__(
        self,
        switch_id: str,
        last_disarm: int,
        last_touched: int,
        expiration_minutes: int = DEFAULT_EXPIRATION_MINUTES,
        is_enabled: bool = True
    ):
        self.switch_id = switch_id
        self.last_disarm = last_disarm
        self.last_touched = last_touched
        self.expiration_minutes = expiration_minutes
        self.is_enabled = is_enabled

    def get_selector(
        self
    ):
        return {
            'switch_id': self.switch_id
        }

    def get_seconds_remaining(
        self
    ):
        return self.expiration - DateTimeUtil.timestamp()

    @staticmethod
    def from_entity(data):
        return Switch(
            switch_id=data.get('switch_id'),
            last_disarm=data.get('last_disarm'),
            last_touched=data.get('last_touched'),
            expiration_minutes=data.get('expiration_minutes'),
            is_enabled=data.get('is_enabled'))
