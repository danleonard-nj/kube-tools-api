import json
import uuid
from unittest.mock import Mock

from framework.dependency_injection.container import Dependency, DependencyType
from framework.middleware.authorization import AuthMiddleware

from utilities.provider import ContainerProvider


def inject_test_dependency(_type, instance):
    container = ContainerProvider.get_container()
    container._container[_type] = Dependency(
        _type=_type,
        reg_type=DependencyType.SINGLETON,
        instance=instance)


def inject_mock_middleware():
    auth_middleware = Mock()
    auth_middleware.validate_access_token = Mock(
        return_value=True)

    inject_test_dependency(
        _type=AuthMiddleware,
        instance=auth_middleware)


class MockResponse:
    def __init__(self, status_code, json=None, text=None, content=None):
        self.status_code = status_code
        self._json = json
        self._text = text
        self._content = content

    def json(self):
        return self._json

    @property
    def text(self):
        return self._text or json.dumps(self._json)

    @property
    def content(self):
        return self._content


class MockContainer:
    def __init__(self):
        self.returns = {}

    def define(self, _type, obj):
        self.returns[_type] = obj

    def resolve(self, _type):
        return self.returns.get(_type) or Mock()


def guid():
    return str(uuid.uuid4())


def get_test_data(name):
    with open(f'./tests/data/{name}', 'r') as file:
        return json.loads(file.read())
