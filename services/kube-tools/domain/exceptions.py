import httpx


class GoogleFitRequestFailedException(Exception):
    def __init__(self, response: httpx.Response, *args: object) -> None:
        super().__init__(
            f'Request failed: {self.__get_failure_message(response)}')

    def __get_failure_message(
        self,
        response: httpx.Response
    ):
        return f'{response.url}: {response.status_code}'


class GoogleFitAuthenticationException(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__('Failed to fetch OAuth token for Google Fit client')


class AcrPurgeServiceParameterException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class AzureGatewayLogRequestException(Exception):
    def __init__(self, message, *args: object) -> None:
        super().__init__(message)


class InvalidSchemaException(Exception):
    def __init__(self, data, *args: object) -> None:
        super().__init__(f'Invalid RSS schema: {data}')
