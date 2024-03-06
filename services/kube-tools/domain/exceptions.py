
class AcrPurgeServiceParameterException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class AzureGatewayRequestException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class AuthClientNotFoundException(Exception):
    def __init__(
        self,
        client_name: str,
        *args: object
    ) -> None:
        super().__init__(
            f"No registered client with the name '{client_name}' could be found"
        )


class AuthTokenFailureException(Exception):
    def __init__(
        self,
        client_name: str,
        status_code: int,
        message: str,
        *args: object
    ) -> None:
        super().__init__(
            f"Failed to fetch auth token for client '{client_name}' with status '{status_code}': {message}"
        )


class EmailRuleExistsException(Exception):
    def __init__(self, name: str, *args: object) -> None:
        super().__init__(
            f"A rule with the name '{name}' exists")


class EmailRuleNotFoundException(Exception):
    def __init__(self, rule_id, *args: object) -> None:
        super().__init__(
            f"No rule with the '{rule_id}' exists"
        )


class ChatGptException(Exception):
    def __init__(self, message, status_code, gpt_error, *args: object) -> None:
        self.status_code = status_code
        self.gpt_error = gpt_error
        self.message = messag

        self.retry = (
            status_code == 429
            or status_code == 503
        )

        super().__init__(message)


class InvalidBankKeyException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class GmailRuleProcessingException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class InvalidGoogleAuthClientException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class GmailBalanceSyncException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class InvalidTorrentSearchException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class PodcastConfigurationException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class UsageRangeException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)
