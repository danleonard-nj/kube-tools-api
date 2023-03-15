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
        data
    ):
        self.name = data.get('name')
        self.description = data.get('description')
        self.query = data.get('query')
        self.action = data.get('sms')
        self.data = data.get('data')
        self.max_results = data.get('max_results')
        self.created_date = data.get('created_date')
