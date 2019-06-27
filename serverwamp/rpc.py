import inspect
from collections import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, MutableMapping, Union

from serverwamp.helpers import camel_to_snake
from serverwamp.protocol import WAMPRPCErrorResponse, WAMPRPCResponse

POSITIONAL_PARAM_KINDS = frozenset({
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD
})
PARAM_PASSTHROUGH_TYPES = frozenset({str, inspect.Parameter.empty})


class WAMPNoSuchProcedureError(Exception):
    pass


class Router:
    def __init__(self, camel_snake_conversion=False):
        self.dispatch_table: MutableMapping[str, Callable[..., Awaitable]] = {}
        self.camel_snake_conversion = camel_snake_conversion

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

    async def handle_rpc_call(
        self,
        rpc_request
    ) -> Union[WAMPRPCResponse, WAMPRPCErrorResponse]:
        procedure = self.resolve(rpc_request.uri)

        if self.camel_snake_conversion:
            request_kwargs = {
                camel_to_snake(k): v
                for k, v
                in rpc_request.kwargs.items()
            }
        else:
            request_kwargs = rpc_request.kwargs.copy()

        special_params = {
            'request': rpc_request,
            'session': rpc_request.session
        }

        request_arg_values = iter(rpc_request.args)
        call_args = []
        call_kwargs: Mapping[Any, Any] = {}  # TODO: populate for kwarg-onlies

        for name, param in inspect.signature(procedure).parameters.items():
            is_passthrough = param.annotation in PARAM_PASSTHROUGH_TYPES

            if name in special_params:
                call_args.append(special_params[name])
                continue

            value_found = False
            if param.kind in POSITIONAL_PARAM_KINDS:
                try:
                    value = next(request_arg_values)
                except StopIteration:
                    pass
                else:
                    value_found = True
            if not value_found:
                if name in request_kwargs:
                    value = request_kwargs.pop(name)
                elif param.default is not param.empty:
                    value = param.default
                else:
                    return WAMPRPCErrorResponse(
                        rpc_request,
                        uri='wamp.error.invalid_argument',
                        kwargs={'message': f'Argument {name} required.'}
                    )
            call_args.append(
                value
                if is_passthrough or isinstance(value, param.annotation)
                else param.annotation(value)
            )

        try:
            result = await procedure(*call_args, **call_kwargs)
        except RPCError as error:
            return self._response_for_rpc_error(rpc_request, error)
        if isinstance(result, (WAMPRPCResponse, WAMPRPCErrorResponse)):
            return result
        elif isinstance(result, Mapping):
            return WAMPRPCResponse(rpc_request, kwargs=result)
        elif isinstance(result, Sequence):
            return WAMPRPCResponse(rpc_request, args=result)
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
                args=(),
                kwargs=error.error_arguments
            )
        elif isinstance(args, Sequence):
            return WAMPRPCErrorResponse(
                request,
                uri=error.uri,
                args=args
            )
        elif isinstance(args, str):
            return WAMPRPCErrorResponse(
                request,
                uri=error.uri,
                kwargs={
                    'message': error.error_arguments
                }
            )


@dataclass(frozen=True)
class RPCRouteDef:
    uri: str
    handler: Callable[..., Awaitable]
    kwargs: Mapping

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
