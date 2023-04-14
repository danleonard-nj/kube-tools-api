from functools import wraps
from typing import Callable, List

from framework.auth.wrappers.azure_ad_wrappers import azure_ad_authorization
from framework.dependency_injection.provider import (InternalProvider,
                                                     inject_container_async)
from framework.handlers.response_handler_async import response_handler
from quart import Blueprint

from utilities.provider import ContainerProvider


class MetaBlueprint(Blueprint):
    def __get_endpoint(self, view_function: Callable):
        return f'__route__{view_function.__name__}'

    def configure(self,  rule: str, methods: List[str], auth_scheme: str):
        if InternalProvider.container is None:
            ContainerProvider.initialize_provider()

        def decorator(function):
            @self.route(rule, methods=methods, endpoint=self.__get_endpoint(function))
            @response_handler
            @azure_ad_authorization(scheme=auth_scheme)
            @inject_container_async
            @wraps(function)
            async def wrapper(*args, **kwargs):
                return await function(*args, **kwargs)
            return wrapper
        return decorator
