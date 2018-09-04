from collections import Mapping
from collections.abc import Sequence

import attr

from aiohttp_server_wamp.helpers import camel_to_snake
from aiohttp_server_wamp.protocol import WAMPRPCErrorResponse, WAMPRPCResponse


class WAMPNoSuchProcedureError(Exception):
    pass


class Router:
    def __init__(self):
        self.dispatch_table = {}

    def add_route(self, uri, handler):
        self.dispatch_table[uri] = handler

    def resolve(self, uri):
        try:
            handler = self.dispatch_table[uri]
        except KeyError:
            raise WAMPNoSuchProcedureError('Procedure %s does not exist.', uri)
        return handler

    def add_routes(self, routes):
        """Append routes to route table.

        Parameter should be an iterable of RPCRouteDef objects.
        """
        for route_obj in routes:
            route_obj.register(self)

    async def handle_rpc_call(self, rpc_request) -> WAMPRPCResponse:
        command = self.resolve(rpc_request.uri)
        kwargs = {camel_to_snake(k): v for k, v in rpc_request.kwargs.items()}
        try:
            result = await command(*rpc_request.args, **kwargs)
        except RPCError as error:
            return self._response_for_rpc_error(rpc_request, error)
        if isinstance(result, (WAMPRPCResponse, WAMPRPCErrorResponse)):
            return result
        elif isinstance(result, Mapping):
            return WAMPRPCResponse(
                rpc_request, details={}, args=(), kwargs=result)
        elif isinstance(result, Sequence):
            return WAMPRPCResponse(rpc_request, details={}, args=result)
        else:
            raise Exception("Uninterpretable response from RPC handler.")

    @staticmethod
    def _response_for_rpc_error(request, error):
        args = error.error_arguments
        if not args:
            return WAMPRPCErrorResponse(request, uri=error.uri)
        if isinstance(args, Mapping):
            return WAMPRPCErrorResponse(
                request,
                uri=error.uri,
                details={},
                args=(),
                kwargs=error.error_arguments
            )
        elif isinstance(args, Sequence):
            return WAMPRPCErrorResponse(
                request,
                uri=error.uri,
                details={},
                args=error.error_arguments
            )
        elif isinstance(args, str):
            return WAMPRPCErrorResponse(
                request,
                uri=error.uri,
                details={},
                kwargs={
                    'message': error.error_arguments
                }
            )



@attr.s(frozen=True, repr=False, slots=True)
class RPCRouteDef:
    uri = attr.ib(type=str)
    handler = attr.ib()
    kwargs = attr.ib()

    def __repr__(self):
        info = []
        for name, value in sorted(self.kwargs.items()):
            info.append(f', {name}={value!r}')
        return (f'<RPCRouteDef {self.uri} -> {self.handler.__name__!r}'
                f'{"".join(info)}>')

    def register(self, router):
        router.add_route(self.uri, self.handler, **self.kwargs)


def route(uri, handler, **kwargs):
    return RPCRouteDef(uri, handler, kwargs)


class RPCRouteTableDef(Sequence):
    """WAMP RPC route definition table. Similar to aiohttp.web.RouteTableDef"""
    def __init__(self):
        self._items = []

    def __repr__(self):
        return f'<RPCRouteTableDef count={len(self._items)}>'

    def __getitem__(self, index):
        return self._items[index]

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __contains__(self, item):
        return item in self._items

    def route(self, uri, **kwargs):
        def inner(handler):
            self._items.append(RPCRouteDef(uri, handler, kwargs))
            return handler
        return inner


class RPCError(Exception):
    def __init__(self, uri, error_arguments):
        self.uri = uri
        self.error_arguments = error_arguments
