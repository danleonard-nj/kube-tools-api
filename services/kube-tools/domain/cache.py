from framework.crypto.hashing import sha256
from framework.validators.nulls import none_or_whitespace


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
            hashed_scope = sha256(scope)
            return f'auth-{client}-{hashed_scope}'
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
