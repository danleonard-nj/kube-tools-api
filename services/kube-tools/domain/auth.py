import enum
from typing import Dict, List

from framework.serialization import Serializable
from framework.validators.nulls import none_or_whitespace


class AuthClient(enum.StrEnum):
    KubeToolsApi = 'kube-tools-api'


class ClientScope(enum.StrEnum):
    EmailGatewayApi = 'api://4ff83655-c28e-478f-b384-08ca8e98a811/.default'
    TwilioGatewayApi = 'api://608043f8-87a6-46bd-ab49-1b73de73a6ec/.default'
    AzureGatewayApi = 'api://a6d4c26f-f77c-41dc-b732-eb82ac0fbe39/.default'
    ChatGptApi = 'api://ab9e45f0-394f-4688-98bd-7cde2474794e/.default'
    KubeToolsApi = 'api://0d10ce61-5907-4d0b-82e1-d0209f01e678/.default'


class AdRole(enum.StrEnum):
    Execute = 'KubeTools.Execute'
    Banking = 'KubeTools.Banking'


class AuthPolicy(enum.StrEnum):
    Default = 'default'
    Execute = 'execute'
    Banking = 'banking'


class AuthClientConfig(Serializable):
    DefaultGrantType = 'client_credentials'

    def __init__(
        self,
        data: Dict
    ):
        self.client_id = data.get('client_id')
        self.client_secret = data.get('client_secret')

        self.grant_type = data.get(
            'grant_type', self.DefaultGrantType)

        self.scopes = self._parse_scopes(
            scopes=data.get('scopes', list()))

    def _parse_scopes(
        self,
        scopes: List[str]
    ) -> str:

        return ' '.join(scopes)


class AuthRequest(Serializable):
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        grant_type: str,
        scope: str = None
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.grant_type = grant_type
        self.scope = scope

    def to_dict(self) -> Dict:
        req = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': self.grant_type,
        }

        if not none_or_whitespace(self.scope):
            req.update({
                'scope': self.scope
            })

        return req

    @staticmethod
    def from_client(
        client: AuthClientConfig,
        scope: str = None
    ) -> Dict:
        return AuthRequest(
            client_id=client.client_id,
            client_secret=client.client_secret,
            grant_type=client.grant_type,
            scope=scope)
