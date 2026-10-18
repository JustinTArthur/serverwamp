import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from re import Pattern
from typing import Any

from serverwamp.helpers import camel_to_snake
from serverwamp.routing import URIsRouter
from serverwamp.session import WAMPSession

POSITIONAL_PARAM_KINDS = frozenset({
    inspect.Parameter.POSITIONAL_ONLY,
    inspect.Parameter.POSITIONAL_OR_KEYWORD
})
PARAM_PASSTHROUGH_TYPES = frozenset({str, Any, inspect.Parameter.empty})

SIMPLE_VALUE_TYPES = (str, bytes, bytearray, memoryview, int, float, bool)


class WAMPNoSuchProcedureError(Exception):
    pass


@dataclass
class RPCRequest:
    """Information about the call request for RPC handlers.
    """
    id: int
    session: WAMPSession
    uri: str
    args: Sequence
    kwargs: Mapping
    timeout: int = 0
    disclose_caller: bool = False
    receive_progress: bool = False
    partition_route: str | None = None


@dataclass
class RPCResult:
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


class RPCProgressReport(RPCResult):
    """Used to send out intermediate progress results."""


@dataclass
class RPCErrorResult:
    error_uri: str
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


class RPCRouter(URIsRouter):
    async def handle_rpc_call(
        self,
        rpc_request: RPCRequest
    ) -> AsyncIterator[RPCResult | RPCErrorResult]:
        procedure = self.resolve(rpc_request.uri)

        if self.camel_snake_conversion:
            request_kwargs = {
                camel_to_snake(k): v
                for k, v
                in rpc_request.kwargs.items()
            }
        else:
            request_kwargs = dict(rpc_request.kwargs)

        special_params = {
            'request': rpc_request,
            'session': rpc_request.session
        }

        request_arg_values = iter(rpc_request.args)
        call_args: list[Any] = []
        call_kwargs: dict[str, Any] = {}
        params = inspect.signature(procedure).parameters
        var_kwargs_param = None

        try:
            for name, param in params.items():
                if param.kind is param.VAR_POSITIONAL:
                    # Gets the request's args that no other param took.
                    call_args.extend(
                        _converted(name, value, param.annotation)
                        for value in request_arg_values
                    )
                    continue
                if param.kind is param.VAR_KEYWORD:
                    var_kwargs_param = param
                    continue

                # Values the server provides are never taken from the request.
                if name in special_params:
                    value = special_params[name]
                elif name in self.default_arg_factories:
                    value = self.default_arg_factories[name]()
                else:
                    value_found = False
                    if param.kind in POSITIONAL_PARAM_KINDS:
                        try:
                            value = next(request_arg_values)
                        except StopIteration:
                            pass
                        else:
                            value_found = True
                    if not value_found and name in request_kwargs:
                        value = request_kwargs.pop(name)
                        value_found = True

                    if value_found:
                        value = _converted(name, value, param.annotation)
                    elif param.default is not param.empty:
                        value = param.default
                    else:
                        yield RPCErrorResult(
                            error_uri='wamp.error.invalid_argument',
                            kwargs={'message': f'Argument {name} required.'}
                        )
                        return

                if param.kind is param.KEYWORD_ONLY:
                    call_kwargs[name] = value
                else:
                    call_args.append(value)

            if var_kwargs_param:
                # Gets the request's kwargs that aren't named for another param.
                call_kwargs.update(
                    (name, _converted(name, value, var_kwargs_param.annotation))
                    for name, value in request_kwargs.items()
                    if name not in params
                )
        except _InvalidArgument as e:
            yield RPCErrorResult(
                error_uri='wamp.error.invalid_argument',
                kwargs={'message': str(e)}
            )
            return

        procedure_invocation = procedure(*call_args, **call_kwargs)
        if isinstance(procedure_invocation, AsyncIterator):
            try:
                while True:
                    try:
                        return_value = await procedure_invocation.__anext__()
                    except StopAsyncIteration:
                        break
                    result = _yielded_value_to_result(return_value)
                    yield result
                    if not isinstance(result, RPCProgressReport):
                        # Anything other than a progress report is the final
                        # msg.
                        break
            finally:
                aclose = getattr(procedure_invocation, 'aclose', None)
                if aclose:
                    await aclose()
        else:
            return_value = await procedure_invocation
            result = _yielded_value_to_result(return_value)
            yield result


@dataclass(frozen=True)
class RPCRouteDef:
    uri: str
    handler: Callable[..., Awaitable]
    kwargs: Mapping

    def register(self, router):
        router.add_route(self.uri, self.handler, **self.kwargs)


@dataclass(frozen=True)
class RPCPrefixRouteDef:
    uri_prefix: str
    handler: Callable[..., Awaitable]
    kwargs: Mapping

    def register(self, router):
        router.add_prefix_route(self.uri_prefix, self.handler, **self.kwargs)


@dataclass(frozen=True)
class RPCRegexRouteDef:
    uri_pattern: str | Pattern[str]
    handler: Callable[..., Awaitable]
    kwargs: Mapping

    def register(self, router):
        router.add_regex_route(self.uri_pattern, self.handler, **self.kwargs)


def route(uri, handler, **kwargs):
    return RPCRouteDef(uri, handler, kwargs)


class RPCRouteSet(Sequence):
    """WAMP RPC route definition table. Similar to aiohttp.web.RouteTableDef"""
    def __init__(self):
        self._items = []

    def __repr__(self):
        return f'<RPCRouteSet count={len(self._items)}>'

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

    def prefix_route(self, uri_prefix, **kwargs):
        def inner(handler):
            self._items.append(RPCPrefixRouteDef(uri_prefix, handler, kwargs))
            return handler

        return inner

    def regex_route(self, uri_pattern, **kwargs):
        def inner(handler):
            self._items.append(RPCRegexRouteDef(uri_pattern, handler, kwargs))
            return handler

        return inner


RPCHandler = Callable[
    [RPCRequest],
    Awaitable[RPCResult | RPCErrorResult]
    | AsyncIterator[RPCProgressReport | RPCResult | RPCErrorResult]
]


class _InvalidArgument(Exception):
    pass


def _converted(name, value, annotation):
    """Converts a value from a request to a handler param's annotated type if
    it's a class, raising _InvalidArgument if the value can't be.
    """
    if (not isinstance(annotation, type)
            or annotation in PARAM_PASSTHROUGH_TYPES
            or isinstance(value, annotation)):
        return value
    try:
        return annotation(value)
    # ArithmeticError covers the likes of Decimal's InvalidOperation and int()'s
    # OverflowError for infinity.
    except (TypeError, ValueError, ArithmeticError) as e:
        raise _InvalidArgument(
            f'Argument {name} is not a valid {annotation.__name__}.'
        ) from e


def _yielded_value_to_result(yielded_value):
    """Takes a value yielded or returned by a route handler and normalizes it
    as an RPCResult object.
    """
    if isinstance(yielded_value, (RPCResult, RPCErrorResult)):
        return yielded_value
    if isinstance(yielded_value, Mapping):
        return RPCResult(kwargs=yielded_value)
    if yielded_value is None:
        return RPCResult()
    if isinstance(yielded_value, SIMPLE_VALUE_TYPES):
        return RPCResult(args=(yielded_value,))
    if isinstance(yielded_value, Sequence):
        return RPCResult(args=yielded_value)
    else:
        raise Exception('Uninterpretable response from RPC handler.')
