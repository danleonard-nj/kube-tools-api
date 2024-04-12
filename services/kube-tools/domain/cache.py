import hashlib
import json
import uuid
from typing import Any
from framework.validators.nulls import none_or_whitespace
from utilities.utils import KeyUtils


def generate_uuid(data: Any):
    parsed = json.dumps(data, default=str)
    hashed = hashlib.md5(parsed.encode())
    return str(uuid.UUID(hashed.hexdigest()))


class CacheKey:
    @staticmethod
    def auth_token(
        client: str,
        scope: str = None
    ) -> str:
        if not none_or_whitespace(scope):
            hash_key = generate_uuid({
                'client': client,
                'scope': scope
            })
            return f'kube-tools-auth-client-{hash_key}'
        else:
            return f'kube-tools-auth-{client}'

    @staticmethod
    def google_auth_client(
        client_name: str,
        scopes: list[str]
    ) -> str:
        return f'kube-tools-google-auth-client-{client_name}-{generate_uuid(scopes)}'

    @staticmethod
    def chatgpt_service_token(
    ) -> str:
        return f'kube-tools-chatgpt-service-token'

    @staticmethod
    def bank_rule_mapping(
    ) -> str:
        return f'kube-tools-bank-rule-mapping'

    @staticmethod
    def weather_cardinality_by_zip(
        zip_code: str
    ) -> str:
        return f'kube-tools-weather-sync-zip-{zip_code}-cardinality-key'

    @staticmethod
    def weather_by_zip(
        zip_code: str
    ) -> str:
        return f'kube-tools-weather-zip-{zip_code}'

    @staticmethod
    def weather_forecast_by_zip(
        zip_code: str
    ) -> str:
        return f'kube-tools-weather-forecast-zip-{zip_code}'

    @staticmethod
    def chat_gpt_response_by_balance_prompt(
        balance_prompt: str
    ) -> str:

        key = KeyUtils.create_uuid(
            balance_prompt=balance_prompt)

        return f'kube-tools-gpt-balance-prompt-{key}'
