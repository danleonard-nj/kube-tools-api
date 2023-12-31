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


def create_key(**kwargs):
    return generate_uuid(kwargs)


class CacheKey:
    @staticmethod
    def azure_gateway_usage_key(
        url: str
    ):
        return f'azure-gateway-usage-{url}'

    @staticmethod
    def azure_gateway_token() -> str:
        return 'azure-gateway-client-token'

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
            return f'auth-client-{hash_key}'
        else:
            return f'auth-{client}'

    @staticmethod
    def gmail_token() -> str:
        return 'gmail-oauth-token'

    @staticmethod
    def google_drive_token() -> str:
        return 'google-drive-oauth-token'

    @staticmethod
    def google_nest_auth_token() -> str:
        return 'google-nest-auth-token'

    @staticmethod
    def nest_device_grouped_sensor_data(
        device_id,
        key
    ) -> str:
        hash_key = KeyUtils.create_uuid(
            device_id=device_id,
            key=key)

        return f'google-nest-gsd-{hash_key}'

    @staticmethod
    def nest_device(
        device_id: str
    ) -> str:
        return f'google-nest-device-{device_id}'

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

        return f'gpt-balance-prompt-{key}'
