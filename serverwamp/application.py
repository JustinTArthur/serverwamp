import inspect
import logging
import warnings
from collections import defaultdict
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Collection,
    Mapping,
    MutableMapping,
    MutableSequence,
    MutableSet,
)
from dataclasses import dataclass
from hashlib import sha256
from hmac import new as new_hmac
from typing import Any

from serverwamp.adapters.async_base import AsyncSupport
from serverwamp.connection import ConnectionClosed
from serverwamp.events import SubscriptionHandler, TopicsRouter
from serverwamp.protocol import (
    WAMPGoodbyeRequest,
    WAMPHelloRequest,
    WAMPMsgParseError,
    WAMPRPCRequest,
    WAMPSubscribeRequest,
    WAMPUnsubscribeRequest,
    call_error_response_msg,
    call_result_response_msg,
    subscribe_error_response_msg,
    unsubscribe_error_response_msg,
    wamp_request_from_msg,
)
from serverwamp.routing import NoSuchRouteError
from serverwamp.rpc import RPCErrorResult, RPCHandler, RPCProgressReport, RPCRequest, RPCRouter
from serverwamp.session import NoSuchSubscription, WAMPSession

ALWAYS_SYNCHRONIZE = frozenset((WAMPGoodbyeRequest, WAMPSubscribeRequest, WAMPUnsubscribeRequest))
EMPTY_SET: frozenset[Any] = frozenset()

logger = logging.getLogger(__name__)

# Each handler takes requests of the type it's mapped from, which a mapping
# type can't express, so its request parameter is typed as Any.
ProtocolRequestHandler = Callable[[Any, WAMPSession], Awaitable[None]]
ProtocolRequestHandlerMap = Mapping[type, ProtocolRequestHandler]
MutableProtocolRequestHandlerMap = MutableMapping[type, ProtocolRequestHandler]

CoreAuthenticator = Callable[[WAMPSession], Awaitable[None]]
TransportAuthenticator = Callable[[WAMPSession], Awaitable[Any]]
TicketAuthenticator = Callable[[WAMPSession, str], Awaitable[Any]]


@dataclass
class CRAAuthRequirement:
    secret: bytes
    auth_role: str
    auth_provider: str


CRARequirementProvider = Callable[[WAMPSession], Awaitable[CRAAuthRequirement]]
CRAIdentityProvider = Callable[[WAMPSession], Awaitable[Any]]

# Lifespans take any of the session and default args, by parameter name.
SessionLifespan = Callable[..., AsyncIterator[None]]


def __getattr__(name):
    if name == 'SessionStateHandler':
        warnings.warn(
            'SessionStateHandler is deprecated; use SessionLifespan instead.',
            DeprecationWarning,
            stacklevel=2
        )
        return SessionLifespan
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')


class Realm:
    def __init__(self, uri: str | None = None):
        self.uri = uri
        self.authenticate_session: CoreAuthenticator = self.default_auth_handler

        self.authed_session_lifespans: MutableSequence[SessionLifespan] = []
        self.session_lifespans: MutableSequence[SessionLifespan] = []

        self._rpc_router = RPCRouter()
        self._topic_router = TopicsRouter()
        self.handle_rpc_call: RPCHandler = self._rpc_router.handle_rpc_call
        self.handle_subscription: SubscriptionHandler = (
            self._topic_router.handle_subscription
        )

        self._default_arg_factories: MutableMapping[str, Callable[[], Any]] = {}

        self._authenticate_ticket: TicketAuthenticator | None = None
        self._transport_authenticators: MutableSequence[TransportAuthenticator] = []
        self._get_cra_requirement: CRARequirementProvider | None = None
        self._identify_cra_session: CRAIdentityProvider | None = None

    def set_authentication_handler(
        self,
        handler: Callable[[WAMPSession], Awaitable[Any]]
    ):
        self.authenticate_session = handler

    def set_rpc_handler(self, handler: RPCHandler):
        self.handle_rpc_call = handler

    def set_subscription_handler(self, handler: SubscriptionHandler):
        self.handle_subscription = handler

    def add_transport_authenticator(
        self,
        transport_authenticator: TransportAuthenticator
    ):
        if transport_authenticator not in self._transport_authenticators:
            self._transport_authenticators.append(transport_authenticator)

    def set_cra_handlers(
        self,
        requirement_provider: CRARequirementProvider,
        identity_provider: CRAIdentityProvider
    ):
        self._get_cra_requirement = requirement_provider
        self._identify_cra_session = identity_provider

    def set_ticket_authenticator(
        self,
        authenticator: TicketAuthenticator
    ):
        self._authenticate_ticket = authenticator

    def add_session_lifespan(
        self,
        lifespan: SessionLifespan,
        authenticated_only=True
    ):
        """Adds an async generator function to run over each session's
        lifespan. It runs to its ``yield`` when the session starts, or once
        it's authenticated if ``authenticated_only`` is true, and the rest
        runs when the session ends.
        """
        if authenticated_only:
            self.authed_session_lifespans.append(lifespan)
        else:
            self.session_lifespans.append(lifespan)

    def add_session_state_handler(
        self,
        handler: SessionLifespan,
        authenticated_only=True
    ):
        warnings.warn(
            'add_session_state_handler() is deprecated; use '
            'add_session_lifespan() instead.',
            DeprecationWarning,
            stacklevel=2
        )
        self.add_session_lifespan(handler, authenticated_only)

    @property
    def authed_session_state_handlers(self) -> MutableSequence[SessionLifespan]:
        warnings.warn(
            'authed_session_state_handlers is deprecated; use '
            'authed_session_lifespans instead.',
            DeprecationWarning,
            stacklevel=2
        )
        return self.authed_session_lifespans

    @property
    def session_state_handlers(self) -> MutableSequence[SessionLifespan]:
        warnings.warn(
            'session_state_handlers is deprecated; use session_lifespans '
            'instead.',
            DeprecationWarning,
            stacklevel=2
        )
        return self.session_lifespans

    def set_default_arg(
        self,
        arg_name,
        value: Any = None,
        factory: Callable | None = None
    ) -> None:
        self._rpc_router.set_default_arg(arg_name, value, factory)
        self._topic_router.set_default_arg(arg_name, value, factory)
        self._default_arg_factories[arg_name] = ((lambda: value)
                                                 if factory is None
                                                 else factory)

    def add_rpc_routes(self, routes):
        self._rpc_router.add_routes(routes)

    def add_topic_routes(self, routes):
        self._topic_router.add_routes(routes)

    def args_for_realm_level_handler(self, handler, **special_params):
        """Used internally by a serverwamp application to determine the args
        and kwargs to call a configured handler with (e.g. session lifespan).

        Raises TypeError for a parameter that isn't a special param or default
        arg and has no default value.
        """
        handler_args = []
        handler_kwargs = {}
        skipped_positional_only = False
        for name, param in inspect.signature(handler).parameters.items():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            if name in special_params:
                value = special_params[name]
            elif name in self._default_arg_factories:
                value = self._default_arg_factories[name]()
            elif param.default is not param.empty:
                if param.kind is param.POSITIONAL_ONLY:
                    skipped_positional_only = True
                continue
            else:
                raise TypeError(
                    f'No value for parameter {name!r} of {handler!r}. It '
                    f'needs a default value, or a default arg of that name '
                    f'set with set_default_arg().'
                )

            if param.kind is not param.POSITIONAL_ONLY:
                handler_kwargs[name] = value
            elif skipped_positional_only:
                raise TypeError(
                    f'No value for positional-only parameter {name!r} of '
                    f'{handler!r} can be given, as it follows one left to '
                    f'its default value.'
                )
            else:
                handler_args.append(value)
        return handler_args, handler_kwargs

    async def default_auth_handler(self, session):
        if not (
            self._transport_authenticators
            or self._authenticate_ticket
            or self._get_cra_requirement
        ):
            await session.mark_authenticated(None)
            return

        for authenticate in self._transport_authenticators:
            identity = await authenticate(session)
            if identity:
                await session.mark_authenticated(identity)
                return

        if 'wampcra' in session.auth_methods and self._get_cra_requirement:
            cra_requirement = await (
                self._get_cra_requirement(session)
            )
            response = await session.request_cra_auth(
                cra_requirement.auth_role,
                cra_requirement.auth_provider
            )
            if verify_cra_response(response, cra_requirement.secret):
                identity = await self._identify_cra_session(session)
                if identity:
                    await session.mark_authenticated(identity)
                    return
        elif 'ticket' in session.auth_methods and self._authenticate_ticket:
            ticket = await session.request_ticket_auth()
            identity = await self._authenticate_ticket(session, ticket)
            if identity:
                await session.mark_authenticated(identity)
                return

        await session.abort(uri='wamp.error.authentication_failed',
                            message='Authentication failed.')


async def abort_on_malformed_msgs(msgs, connection):
    """Passes along a connection's messages until the transport can't
    deserialize one, then aborts the connection and stops. Without this, the
    deserialization error would escape the connection handler without the
    client being told why.
    """
    try:
        async for msg in msgs:
            yield msg
    except WAMPMsgParseError:
        await connection.abort('wamp.error.protocol_violation', 'Parse error.')


async def advance(async_iter):
    """Awaits an async iterator's next item from a coroutine, as some async
    supports only spawn coroutines, not other awaitables like __anext__()'s.
    """
    await async_iter.__anext__()


@dataclass
class CRAResponse:
    signature: str
    challenge: str


class Application:
    def __init__(
        self,
        allow_default_realm=True,
        async_support: type[AsyncSupport] | None = None,
        synchronize_requests: bool = False,
        protocol_request_handlers: ProtocolRequestHandlerMap | None = None,
    ):
        if async_support:
            self._async_support = async_support
        else:
            from serverwamp.adapters.asyncio import AsyncioAsyncSupport
            self._async_support = AsyncioAsyncSupport
        self._realms: MutableMapping[str, Realm] = {}

        self._default_realm = Realm() if allow_default_realm else None

        self._protocol_request_handlers: MutableProtocolRequestHandlerMap = {
            WAMPGoodbyeRequest: default_protocol_goodbye_handler,
            WAMPRPCRequest: default_protocol_rpc_handler,
            WAMPSubscribeRequest: self.default_protocol_subscribe_handler,
            WAMPUnsubscribeRequest: self.default_protocol_unsubscribe_handler
        }

        if protocol_request_handlers:
            self._protocol_request_handlers.update(protocol_request_handlers)

        self._synchronize_requests = synchronize_requests

        self._active_sessions: MutableSet[WAMPSession] = set()
        self._subscription_exits: MutableMapping[
            WAMPSession, MutableMapping[int, AsyncIterator]
        ] = defaultdict(dict)
        self._session_lifespan_exits: MutableMapping[
            WAMPSession, MutableSet[AsyncIterator]
        ] = defaultdict(set)

    def add_realm(self, realm):
        self._realms[realm.uri] = realm

    async def handle_session(
        self,
        session: WAMPSession,
        msgs: AsyncIterator | None = None
    ) -> bool:
        """Runs an established session until it ends, returning whether it
        ended with GOODBYE, after which the client may start another session
        on the same connection.
        """
        self._active_sessions.add(session)
        connection = session.connection
        realm: Realm = session.realm

        if realm.session_lifespans:
            await self._start_session_lifespans(
                realm.session_lifespans,
                session
            )

        await realm.authenticate_session(session)
        if not session.is_open:
            return False

        if realm.authed_session_lifespans:
            await self._start_session_lifespans(
                realm.authed_session_lifespans,
                session
            )

        if msgs is None:
            msgs = abort_on_malformed_msgs(connection.iterate_msgs(),
                                           connection)
        return await self._process_protocol_msgs(msgs, connection, session)

    async def handle_connection(self, connection):
        # A single iterator serves the whole connection so that messages the
        # transport already received, like the rest of a batch, aren't lost.
        msgs = connection.iterate_msgs()
        checked_msgs = abort_on_malformed_msgs(msgs, connection)
        try:
            await self._handle_connection_msgs(connection, checked_msgs)
        finally:
            await checked_msgs.aclose()
            aclose = getattr(msgs, 'aclose', None)
            if aclose:
                await aclose()

    async def _handle_connection_msgs(self, connection, msgs):
        # The spec lets a client open another session after GOODBYE, so the
        # connection can carry one session after another.
        while await self._handle_session_msgs(connection, msgs):
            pass

    async def _handle_session_msgs(self, connection, msgs) -> bool:
        """Runs a session once the client says hello, returning whether it
        ended with GOODBYE and so the client may say hello again.
        """
        # They say hello or we show them the door.  TODO: timeout?
        async for msg in msgs:
            try:
                request = wamp_request_from_msg(msg)
            except WAMPMsgParseError:
                await connection.abort('wamp.error.protocol_violation',
                                       'Parse error.')
                return False
            break
        else:
            # Connection closed instead of saying hello.
            return False

        if not isinstance(request, WAMPHelloRequest):
            await connection.abort('wamp.error.protocol_violation',
                                   'Unexpected request.')
            return False

        realm = self._realms.get(request.realm_uri, self._default_realm)
        if realm is None:
            await connection.abort('wamp.error.no_such_realm')
            return False

        async with self._async_support.launch_task_group() as session_tasks:
            session = WAMPSession(
                connection,
                realm,
                tasks=session_tasks,
                auth_id=request.details.get('authid', None),
                auth_methods=request.details.get('authmethods') or ()
            )
            try:
                ended_with_goodbye = await self.handle_session(session, msgs)
            except ConnectionClosed:
                # A reply to a request handled outside a session task, such
                # as with synchronize_requests, outlived the client.
                logger.debug('Session %s disconnected before a reply could '
                             'be sent.', session.id)
                ended_with_goodbye = False
            finally:
                await self._async_support.shield(
                    self._clean_up_session,
                    session
                )
        return ended_with_goodbye

    async def close_sessions(self):
        """Cleanly close active WAMP sessions with goodbye message, such as when
        the server is shutting down.

        Better when clients close their own connections as it won't leave our
        TCP sockets in the TIME-WAIT state.
        """
        async with self._async_support.launch_task_group() as tasks:
            for session in self._active_sessions:
                await tasks.spawn(session.close, 'wamp.close.system_shutdown')

    async def _process_protocol_msgs(
        self,
        msgs,
        connection,
        session
    ) -> bool:
        # Once the session is authenticated, order is not important to the WAMP
        # protocol itself; messages expecting responses have identifiers for
        # referring back to them. Ordering may still be important to the app,
        # however.
        async for msg in msgs:
            try:
                request = wamp_request_from_msg(msg)
            except WAMPMsgParseError:
                await connection.abort('wamp.error.protocol_violation',
                                       'Parse error.')
                return False
            request_type = type(request)
            handler = self._protocol_request_handlers.get(request_type)
            if handler is None:
                # Such as a HELLO for a session that's already established.
                await connection.abort('wamp.error.protocol_violation',
                                       'Unexpected request.')
                return False
            if not session.is_open and request_type is not WAMPGoodbyeRequest:
                # The session was closed, so per the spec, anything but the
                # client's GOODBYE in reply is ignored.
                continue
            if (self._synchronize_requests
                    or request_type in ALWAYS_SYNCHRONIZE):
                await handler(request, session)
            else:
                await session.spawn_task(handler, request, session)
            if request_type is WAMPGoodbyeRequest and not session.is_open:
                # GOODBYE has been said both ways, which ends the session.
                return True
        # The client disconnected.
        return False

    async def _clean_up_session(self, session):
        self._active_sessions.discard(session)
        subscription_exits = self._subscription_exits.pop(session, {})
        for subscribe_unsubscribe_iter in subscription_exits.values():
            try:
                await subscribe_unsubscribe_iter.__anext__()
            except StopAsyncIteration:
                pass
            else:
                logger.error(
                    'Subscription manager %s for session %s has more than two '
                    'iterations or more than one yield.',
                    subscribe_unsubscribe_iter, session.id
                )

        lifespan_iters = self._session_lifespan_exits.pop(session, EMPTY_SET)
        if lifespan_iters:
            # TODO, make exits concurrent
            for lifespan_iter in lifespan_iters:
                try:
                    await lifespan_iter.__anext__()
                except StopAsyncIteration:
                    pass
                else:
                    logger.error(
                        'Session lifespan %s for session %s has more than two '
                        'iterations or more than one yield.',
                        lifespan_iter, session.id
                    )

    # Default Realm Configuration…
    @property
    def _enabled_default_realm(self) -> Realm:
        if self._default_realm is None:
            raise RuntimeError(
                'The default realm is disabled by allow_default_realm=False. '
                'Configure a Realm and add it with Application.add_realm() '
                'instead.'
            )
        return self._default_realm

    def set_authentication_handler(
        self,
        handler: Callable[[WAMPSession], Awaitable[Any]]
    ):
        self._enabled_default_realm.set_authentication_handler(handler)

    def set_rpc_handler(self, handler: RPCHandler):
        self._enabled_default_realm.set_rpc_handler(handler)

    def set_subscription_handler(self, handler: SubscriptionHandler):
        self._enabled_default_realm.set_subscription_handler(handler)

    def add_transport_authenticator(
        self,
        authenticator: TransportAuthenticator
    ):
        self._enabled_default_realm.add_transport_authenticator(authenticator)

    def set_cra_handlers(
        self,
        requirement_provider: CRARequirementProvider,
        identity_provider: CRAIdentityProvider
    ):
        self._enabled_default_realm.set_cra_handlers(
            requirement_provider,
            identity_provider
        )

    def set_ticket_authenticator(
        self,
        authenticator: TicketAuthenticator
    ):
        self._enabled_default_realm.set_ticket_authenticator(authenticator)

    def add_session_lifespan(self, lifespan: SessionLifespan, authenticated_only=True):
        self._enabled_default_realm.add_session_lifespan(lifespan, authenticated_only)

    def add_session_state_handler(self, handler: SessionLifespan, authenticated_only=True):
        warnings.warn(
            'add_session_state_handler() is deprecated; use '
            'add_session_lifespan() instead.',
            DeprecationWarning,
            stacklevel=2
        )
        self._enabled_default_realm.add_session_lifespan(handler, authenticated_only)

    def set_default_arg(
        self,
        arg_name,
        value: Any = None,
        factory: Callable | None = None
    ) -> None:
        self._enabled_default_realm.set_default_arg(arg_name, value, factory)

    def add_rpc_routes(self, routes):
        self._enabled_default_realm.add_rpc_routes(routes)

    def add_topic_routes(self, routes):
        self._enabled_default_realm.add_topic_routes(routes)

    async def _start_session_lifespans(self, lifespans, session):
        async with self._async_support.launch_task_group() as start_tasks:
            for lifespan in lifespans:
                args, kwargs = session.realm.args_for_realm_level_handler(
                    lifespan,
                    session=session
                )
                lifespan_iter = lifespan(*args, **kwargs)
                await start_tasks.spawn(advance, lifespan_iter)
                self._session_lifespan_exits[session].add(lifespan_iter)

    async def default_protocol_subscribe_handler(
        self,
        request: WAMPSubscribeRequest,
        session: WAMPSession
    ):
        sub_id = session.subscription_id_for_topic(request.topic)
        if sub_id in self._subscription_exits[session]:
            # Already subscribed. Per the WAMP spec, answer with the existing
            # subscription rather than starting another.
            await session.mark_subscribed(request, sub_id)
            return

        await session.register_subscription(request.topic)
        subscribe_unsubscribe_iter = session.realm.handle_subscription(request.topic, session)
        try:
            await subscribe_unsubscribe_iter.__anext__()
        except NoSuchRouteError:
            # Only topics the application routes can be subscribed to.
            await session.unregister_subscription(sub_id)
            await session.send_raw(
                subscribe_error_response_msg(request, 'wamp.error.invalid_uri')
            )
            return
        self._subscription_exits[session][sub_id] = subscribe_unsubscribe_iter
        await session.mark_subscribed(request, sub_id)

    async def default_protocol_unsubscribe_handler(
        self,
        request: WAMPUnsubscribeRequest,
        session: WAMPSession
    ):
        subscribe_unsubscribe_iter = self._subscription_exits[session].pop(
            request.subscription,
            None
        )
        if subscribe_unsubscribe_iter:
            try:
                await subscribe_unsubscribe_iter.__anext__()
            except StopAsyncIteration:
                pass
            else:
                logger.error('Unsubscribe iterator %s had more than two '
                             'iterations, such as from more than one yield '
                             'statement.', subscribe_unsubscribe_iter)
        try:
            await session.unregister_subscription(request.subscription)
        except NoSuchSubscription:
            await session.send_raw(
                unsubscribe_error_response_msg(
                    request,
                    'wamp.error.no_such_subscription'
                )
            )
        else:
            await session.mark_unsubscribed(request)

    # Support for various web servers/frameworks

    def aiohttp_websocket_handler(self):
        from serverwamp.adapters.aiohttp import connection_for_aiohttp_request

        async def handle_aiohttp_request(request):
            connection = await connection_for_aiohttp_request(request)
            await self.handle_connection(connection)
            return connection.ws_response

        return handle_aiohttp_request

    def asgi_application(
        self,
        paths: Collection[str] | None = None
    ):
        """Returns an ASGI application callable that serves WAMP on the given
        paths. Other paths will return a 404. If paths is omitted, any path
        requested by the user agent will serve WAMP sessions.
        """
        from serverwamp.adapters.asgi import (
            connection_for_asgi_invocation,
            handle_asgi_lifespan,
            handle_asgi_path_not_found,
        )

        async def application_callable(
            scope: Mapping,
            receive: Callable[[], Awaitable[Mapping]],
            send: Callable[[Mapping], Awaitable]
        ) -> None:
            if scope['type'] == 'lifespan':
                return await handle_asgi_lifespan(receive, send)
            if paths and scope['path'] not in paths:
                return await handle_asgi_path_not_found(scope, receive, send)
            connection = await connection_for_asgi_invocation(scope, receive,
                                                              send)
            if connection is None:
                # Not a WAMP WebSocket request, so it was turned away.
                return
            await self.handle_connection(connection)
        return application_callable

    def legacy_asgi_application(
        self,
        paths: Collection[str] | None = None
    ):
        from serverwamp.adapters.asgi import (
            connection_for_asgi_invocation,
            handle_asgi_lifespan,
            handle_asgi_path_not_found,
        )

        def application_callable(
            scope: Mapping
        ) -> Callable[
            [
                Callable[[], Awaitable[Mapping]],
                Callable[[Mapping], Awaitable]
            ],
            Awaitable
        ]:
            async def application_handler(receive, send):
                if scope['type'] == 'lifespan':
                    return await handle_asgi_lifespan(receive, send)
                if paths and scope['path'] not in paths:
                    return (
                        await handle_asgi_path_not_found(scope, receive, send)
                    )
                connection = await connection_for_asgi_invocation(scope,
                                                                  receive, send)
                if connection is None:
                    # Not a WAMP WebSocket request, so it was turned away.
                    return
                await self.handle_connection(connection)
            return application_handler

        return application_callable


def verify_cra_response(response: CRAResponse, secret: bytes | bytearray):
    hmac = new_hmac(key=secret, msg=response.challenge.encode('utf-8'),
                    digestmod=sha256)
    return response.signature.encode('utf-8') == hmac.digest()


async def default_protocol_rpc_handler(
    request: WAMPRPCRequest,
    session: WAMPSession
):
    partition_route = (
        request.options['rkey']
        if request.options.get('runmode') == 'partition'
        else None
    )
    rpc_request = RPCRequest(
        id=request.request_id,
        session=session,
        uri=request.uri,
        args=request.args,
        kwargs=request.kwargs,
        timeout=request.options.get('timeout', 0),
        disclose_caller=request.options.get('disclose_me', False),
        receive_progress=request.options.get('receive_progress', False),
        partition_route=partition_route
    )
    invocation = session.realm.handle_rpc_call(rpc_request)
    if isinstance(invocation, AsyncIterator):
        try:
            yielded_anything = False
            while True:
                # noinspection PyBroadException
                try:
                    result = await invocation.__anext__()
                except StopAsyncIteration:
                    break
                except Exception:
                    result = RPCErrorResult('wamp.error.runtime_error')
                    logger.exception(
                        'Exception from call handler for procedure %s',
                        request.uri
                    )
                else:
                    yielded_anything = True

                if isinstance(result, RPCProgressReport):
                    await session.send_raw(
                        call_result_response_msg(request, result.args,
                                                 result.kwargs, progress=True)
                    )
                    continue

                # Anything other than a progress report is the final message.

                if isinstance(result, RPCErrorResult):
                    await session.send_raw(
                        call_error_response_msg(request, result.error_uri,
                                                result.args, result.kwargs)

                    )
                    return

                await session.send_raw(
                    call_result_response_msg(request, result.args, result.kwargs)
                )
                return
            if not yielded_anything:
                await session.send_raw(
                    call_error_response_msg(request, 'wamp.error.runtime_error')

                )
                logger.error(
                    'Call handler for procedure %s failed to yield or return a '
                    'result.',
                    request.uri
                )
                return
        finally:
            # Lets the handler clean up right away if the client left before
            # it finished or it yielded past its final result, instead of
            # whenever the event loop finalizes it.
            aclose = getattr(invocation, 'aclose', None)
            if aclose:
                await aclose()

    # noinspection PyBroadException
    try:
        result = await invocation
    except Exception:
        result = RPCErrorResult('wamp.error.runtime_error')
    if isinstance(result, RPCErrorResult):
        await session.send_raw(
            call_error_response_msg(request, result.error_uri,
                                    result.args, result.kwargs)

        )
        return

    await session.send_raw(
        call_result_response_msg(request, result.args, result.kwargs)
    )
    return


async def default_protocol_goodbye_handler(
    request: WAMPGoodbyeRequest,
    session: WAMPSession
):
    await session.close()
