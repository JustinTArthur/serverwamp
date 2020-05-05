import re
from typing import (Any, Awaitable, Callable, MutableMapping, MutableSequence,
                    Optional, Pattern, Tuple, Union)


class URIsRouter:
    """
    Class that holds routes from URIs to asynchronous functions that should
    handle those URIs.
    """
    def __init__(self, camel_snake_conversion=False):
        self._exact_dispatch_table: MutableMapping[
            str, Callable[..., Awaitable]
        ] = {}
        self._pattern_dispatch_table: MutableSequence[
            Tuple[Pattern, Callable[..., Awaitable]]
        ] = []

        self.camel_snake_conversion = camel_snake_conversion
        self.default_arg_factories: MutableMapping[str, Callable[[], Any]] = {}

    def set_default_arg(
        self,
        arg_name,
        value: Optional[Any] = None,
        factory: Optional[Callable[[], Any]] = None,
    ):
        self.default_arg_factories[arg_name] = ((lambda: value)
                                                if factory is None
                                                else factory)

    def add_route(
        self,
        uri: str,
        handler: Callable[..., Awaitable]
    ):
        self._exact_dispatch_table[uri] = handler

    def add_prefix_route(
        self,
        uri_prefix: str,
        handler: Callable[..., Awaitable]
    ):
        # A future implementation might use a faster structure like a trie
        # if available.
        pattern = re.compile(f'^{re.escape(uri_prefix)}')
        self._pattern_dispatch_table.append((pattern, handler))

    def add_regex_route(
        self,
        uri_pattern: Union[str, Pattern],
        handler: Callable
    ):
        if isinstance(uri_pattern, str):
            uri_pattern = re.compile(uri_pattern)
        self._pattern_dispatch_table.append((uri_pattern, handler))

    def resolve(self, uri):
        handler = self._exact_dispatch_table.get(uri)
        if handler:
            return handler
        for uri_pattern, handler in self._pattern_dispatch_table:
            if uri_pattern.match(uri):
                return handler
            return handler

        raise NoSuchRouteError('Procedure %s does not exist.', uri)

    def add_routes(self, routes):
        """Append routes to route table.
        Parameter should be an iterable of RPCRouteDef objects.
        """
        for route_obj in routes:
            route_obj.register(self)


class NoSuchRouteError(Exception):
    """No route was found for the given URI."""
