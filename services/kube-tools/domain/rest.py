from typing import Dict, List, Union

from framework.serialization import Serializable
from quart import Response


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


class GetBalancesResponse(Serializable):
    def __init__(
        self,
        balances: List[Dict],
    ):
        self.balances = balances


class ChatGptCompletionRequest(Serializable):
    def __init__(
        self,
        prompt: str
    ):
        self.prompt = prompt
