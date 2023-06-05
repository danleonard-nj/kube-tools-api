import hashlib
import json
import uuid
from typing import Any

from framework.crypto.hashing import md5
from framework.validators.nulls import none_or_whitespace

from utilities.utils import KeyUtils


def generate_uuid(data: Any):
    parsed = json.dumps(data, default=str)
    hashed = hashlib.md5(parsed.encode())
    return str(uuid.UUID(hashed.hexdigest()))


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
