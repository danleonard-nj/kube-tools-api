import json
from typing import Dict, List, Union

from framework.serialization import Serializable
from quart import Response


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

        degrees_celsius = data.get('degrees_celsius', 0)
        humidity_percent = data.get('humidity_percent', 0)

        self.degrees_celsius = round(degrees_celsius or 0, 2)
        self.humidity_percent = round(humidity_percent or 0, 2)
        self.diagnostics = data.get('diagnostics')


class NestCommandRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.command_type = data.get('command_type')
        self.params = data.get('params')


class NestSensorLogRequest(Serializable):
    def __init__(
        self,
        data: Dict
    ):
        self.device_id = data.get('device_id')
        self.log_level = data.get('log_level')
        self.message = data.get('message')


class ChatGptResponse(Serializable):
    def __init__(
        self,
        body,
        status_code: int,
        headers: Dict
    ):
        self.body = body
        self.status_code = status_code
        self.headers = headers

    def json(self):
        return self.body


class ChatGptProxyResponse(Serializable):
    @property
    def request_body(self):
        return self.__request_body

    @property
    def response(self):
        return self.__response

    @property
    def duration(self):
        return self.__duration

    def __init__(
        self,
        request_body: Dict,
        response: Response,
        duration: float
    ):
        self.__request_body = request_body
        self.__response = response
        self.__duration = duration

    def to_dict(
        self
    ) -> Dict:
        return {
            'request': {
                'body': self.__request_body,
            },
            'response': {
                'body': self.__response.json(),
                'status_code': self.__response.status_code,
                'headers': dict(self.__response.headers),
            },
            'stats': {
                'duration': f'{self.__duration}s'
            }
        }

    @staticmethod
    def from_dict(data: Dict):
        return ChatGptProxyResponse(
            request_body=data.get('request').get('body'),
            response=ChatGptResponse(
                body=data.get('response').get('body'),
                status_code=data.get('response').get('status_code'),
                headers=data.get('response').get('headers')
            ),
            duration=data.get('stats').get('duration')
        )


class ChatGptHistoryEndpointsResponse(Serializable):
    def __init__(
        self,
        results: List[Dict]
    ):
        self.__results = results

    def __group_results(
        self
    ):
        grouped = dict()
        for result in self.__results:
            if grouped.get(result.endpoint) is None:
                grouped[result.endpoint] = []
            grouped[result.endpoint].append(result)

        return grouped

    def to_dict(self) -> Dict:
        grouped = self.__group_results()

        return {
            'endpoints': list(grouped.keys()),
            'data': grouped
        }


class PlaidBalanceRequest(Serializable):
    def __init__(
        self,
        client_id: str,
        secret: str,
        access_token: str
    ):
        self.client_id = client_id
        self.secret = secret
        self.access_token = access_token


class PlaidTransactionRequestOptions(Serializable):
    def __init__(
        self,
        count: int = 500,
        include_personal_finance_category: bool = True,
        account_ids: List[str] = None,
    ):
        self.count = count
        self.include_personal_finance_category = include_personal_finance_category

        if account_ids is not None:
            self.account_ids = account_ids


class PlaidTransactionsRequest(Serializable):
    def __init__(
        self,
        client_id: str,
        secret: str,
        access_token: str,
        start_date: str,
        end_date: str,
        options: Union[PlaidTransactionRequestOptions, Dict] = None
    ):
        self.client_id = client_id
        self.secret = secret
        self.access_token = access_token
        self.start_date = start_date
        self.end_date = end_date

        if options is not None:
            if isinstance(options, PlaidTransactionRequestOptions):
                self.options = options.to_dict()
            else:
                self.options = options
