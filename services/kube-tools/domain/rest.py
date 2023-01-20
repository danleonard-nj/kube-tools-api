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
