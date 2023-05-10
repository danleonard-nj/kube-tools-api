from typing import Dict, List
from framework.serialization import Serializable


class AuthorizationHeader(Serializable):
    def __init__(
        self,
        token: str
    ):
        self.bearer = token

    def to_dict(self):
        return {
            'Authorization': f'Bearer {self.bearer}'
        }


class GmailModifyEmailRequest(Serializable):
    def __init__(
        self,
        add_label_ids: List = [],
        remove_label_ids: List = []
    ):
        self.add_label_ids = add_label_ids
        self.remove_label_ids = remove_label_ids

    def to_dict(self) -> Dict:
        return {
            "addLabelIds": self.add_label_ids,
            "removeLabelIds": self.remove_label_ids
        }


class CreateEmailRuleRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.name = data.get('name')
        self.description = data.get('description')
        self.query = data.get('query')
        self.action = data.get('action')
        self.data = data.get('data')
        self.max_results = data.get('max_results')


class UpdateEmailRuleRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.rule_id = data.get('rule_id')
        self.name = data.get('name')
        self.description = data.get('description')
        self.query = data.get('query')
        self.action = data.get('action')
        self.data = data.get('data')
        self.max_results = data.get('max_results')


class CreateDeadManConfigurationRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.configuration_name = data.get('configuration_name')
        self.interval_hours = data.get('interval_hours')
        self.grace_period_hours = data.get('grace_period_hours')
        self.alert_type = data.get('alert_type')
        self.alert_address = data.get('alert_address')


class UpdateDeadManConfigurationRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.configuration_id = data.get('configuration_id')
        self.interval_hours = data.get('interval_hours')
        self.grace_period_hours = data.get('grace_period_hours')
        self.alert_type = data.get('alert_type')
        self.alert_address = data.get('alert_address')


class CreateSwitchRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.switch_name = data.get('switch_name')
        self.configuration_id = data.get('configuration_id')


class DisarmSwitchRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.switch_id = data.get('switch_id')


class DeleteGmailEmailRuleResponse(Serializable):
    def __init__(
        self,
        result: bool
    ):
        self.result = result


class SaveNestAuthCredentialRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.client_id = data.get('client_id')
        self.client_secret = data.get('client_secret')
        self.refresh_token = data.get('refresh_token')


class NestSensorDataRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.sensor_id = data.get('sensor_id')
        self.degrees_celsius = data.get('degrees_celsius')
        self.humidity_percent = data.get('humidity_percent')
