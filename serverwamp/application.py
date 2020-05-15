import inspect
from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from hmac import HMAC
from typing import (Any, AsyncIterator, Awaitable, Callable, Collection,
                    Mapping, MutableMapping, MutableSequence, MutableSet,
                    Optional, Type, Union)

from serverwamp.adapters.async_base import AsyncSupport
from serverwamp.events import SubscriptionHandler, TopicsRouter
from serverwamp.protocol import (WAMPGoodbyeRequest, WAMPHelloRequest,
                                 WAMPMsgParseError, WAMPRequest,
                                 WAMPRPCRequest, WAMPSubscribeRequest,
                                 WAMPUnsubscribeRequest,
                                 call_error_response_msg,
                                 call_result_response_msg,
                                 unsubscribe_error_response_msg,
                                 wamp_request_from_msg)
from serverwamp.rpc import (RPCErrorResult, RPCHandler, RPCProgressReport,
                            RPCRequest, RPCRouter)
from serverwamp.session import NoSuchSubscription, WAMPSession

EMPTY_SET = frozenset()

ProtocolRequestHandlerMap = Mapping[
    Type[WAMPRequest],
    Callable[[WAMPRequest, WAMPSession], Awaitable[None]]
]
MutableProtocolRequestHandlerMap = MutableMapping[
    Type[WAMPRequest],
    Callable[[WAMPRequest, WAMPSession], Awaitable[None]]
]

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

SessionStateHandler = Callable[[WAMPSession], AsyncIterator[None]]


class Realm:
    def __init__(self, uri: Optional[str] = None):
        self.uri = uri
        self.authenticate_session: CoreAuthenticator = self.default_auth_handler

        self.authed_session_state_handlers: MutableSequence[SessionStateHandler] = []
        self.session_state_handlers: MutableSequence[SessionStateHandler] = []

        self._rpc_router = RPCRouter()
        self._topic_router = TopicsRouter()
        self.handle_rpc_call = self._rpc_router.handle_rpc_call
        self.handle_subscription = self._topic_router.handle_subscription

        self._default_arg_factories: MutableMapping[str, Callable[[], Any]] = {}

        self._authenticate_ticket: Optional[TicketAuthenticator] = None
        self._transport_authenticators: MutableSequence[TransportAuthenticator] = []
        self._get_cra_requirement: Optional[CRARequirementProvider] = None
        self._identify_cra_session: Optional[CRAIdentityProvider] = None

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

    def add_session_state_handler(
        self,
        handler: SessionStateHandler,
        authenticated_only=True
    ):
        if authenticated_only:
            self.authed_session_state_handlers.append(handler)
        else:
            self.session_state_handlers.append(handler)

    def set_default_arg(
        self,
        arg_name,
        value: Optional[Any] = None,
        factory: Optional[Callable] = None
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
        """Used internally by a serverwamp application to determine what args
        to call a configured handler with (e.g. session state handler)
        """
        handler_args = []
        for name in inspect.signature(handler).parameters.keys():
            if name in special_params:
                handler_args.append(special_params[name])
                continue
            elif name in self._default_arg_factories:
                handler_args.append(self._default_arg_factories[name]())
            else:
                """TODO: Raise error to client."""
        return handler_args

    async def default_auth_handler(self, session):
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


@dataclass
class CRAResponse:
    signature: str
    challenge: str


class Application:
    def __init__(
        self,
        allow_default_realm=True,
        async_support: Optional[Type[AsyncSupport]] = None,
        synchronize_requests: bool = False,
        protocol_request_handlers: Optional[ProtocolRequestHandlerMap] = None,
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

        self._subscription_exits: MutableMapping[
            WAMPSession, MutableMapping[int, AsyncIterator]
        ] = defaultdict(dict)
        self._session_state_exits: MutableMapping[
            WAMPSession, MutableSet[AsyncIterator]
        ] = defaultdict(set)

    def add_realm(self, realm):
        self._realms[realm.uri] = realm

    async def handle_session(self, session: WAMPSession):
        connection = session.connection
        realm: Realm = session.realm

        if realm.session_state_handlers:
            await self._start_session_state_handlers(
                realm.session_state_handlers,
                session
            )
            async with self._async_support.launch_task_group() as start_tasks:
                for handler in realm.session_state_handlers:
                    args = realm.args_for_realm_level_handler(handler)
                    state_iter = handler(*args)
                    await start_tasks.spawn(state_iter.__anext__)
                    self._session_state_exits[session].add(state_iter)

        await realm.authenticate_session(session)
        if not session.is_open:
            return

        if realm.authed_session_state_handlers:
            await self._start_session_state_handlers(
                realm.authed_session_state_handlers,
                session
            )

        # Once the session is authenticated, order is not important to the WAMP
        # protocol itself; messages expecting responses have identifiers for
        # referring back to them. Ordering may still be important to the app,
        # however.
        if self._synchronize_requests:
            async for msg in connection.iterate_msgs():
                try:
                    request = wamp_request_from_msg(msg)
                except WAMPMsgParseError:
                    await connection.abort('wamp.error.protocol_error',
                                           'Parse error.')
                    return
                handler = self._protocol_request_handlers[type(msg)]
                await handler(request, session)
            return

        async for msg in connection.iterate_msgs():
            try:
                request = wamp_request_from_msg(msg)
            except WAMPMsgParseError:
                await connection.abort('wamp.error.protocol_error',
                                       'Parse error.')
                return
            handler = self._protocol_request_handlers[type(request)]
            await session.spawn_task(handler, request, session)

        subscription_exits = self._subscription_exits.pop(session, {})
        for subscribe_unsubscribe_iter in subscription_exits.values():
            try:
                await subscribe_unsubscribe_iter.__anext__()
            except StopAsyncIteration:
                pass
            else:
                "TODO: raise exception because there should only be a single yield"

    async def handle_connection(self, connection):
        msgs = connection.iterate_msgs()

        # They say hello or we show them the door.  TODO: timeout?
        async for msg in msgs:
            try:
                request = wamp_request_from_msg(msg)
            except WAMPMsgParseError:
                await connection.abort('wamp.error.protocol_error',
                                       'Parse error.')
                return
            break
        else:
            # Connection closed instead of saying hello.
            return

        if not isinstance(request, WAMPHelloRequest):
            await connection.abort('wamp.error.protocol_error',
                                   'Unexpected request.')
            return

        if request.realm_uri not in self._realms:
            await connection.abort('wamp.error.no_such_realm')
            return
        realm = self._realms[request.realm_uri]

        async with self._async_support.launch_task_group() as session_tasks:
            session = WAMPSession(
                connection,
                realm,
                tasks=session_tasks,
                auth_id=request.details.get('authid', None),
                auth_methods=request.details.get('authmethods', ())
            )
            try:
                await self.handle_session(session)
            finally:
                state_iters = self._session_state_exits.pop(session, EMPTY_SET)
                if state_iters:
                    # TODO, make exits concurrent
                    for state_iter in state_iters:
                        try:
                            await state_iter.__anext__()
                        except StopAsyncIteration:
                            pass
                        else:
                            # TODO: throw exception because there should only
                            # be one more iteration.
                            pass

    # Default Realm Configuration…
    def set_authentication_handler(
        self,
        handler: Callable[[WAMPSession], Awaitable[Any]]
    ):
        self._default_realm.set_authentication_handler(handler)

    def set_rpc_handler(self, handler: RPCHandler):
        self._default_realm.set_rpc_handler(handler)

    def set_subscription_handler(self, handler: SubscriptionHandler):
        self._default_realm.set_subscription_handler(handler)

    def add_transport_authenticator(
        self,
        authenticator: TransportAuthenticator
    ):
        self._default_realm.add_transport_authenticator(authenticator)

    def set_cra_handlers(
        self,
        requirement_provider: CRARequirementProvider,
        identity_provider: CRAIdentityProvider
    ):
        self._default_realm.set_cra_handlers(
            requirement_provider,
            identity_provider
        )

    def set_ticket_authenticator(
        self,
        authenticator: TicketAuthenticator
    ):
        self._default_realm.set_ticket_authenticator(authenticator)

    def add_session_state_handler(self, handler: SessionStateHandler, authenticated_only=True):
        self._default_realm.add_session_state_handler(handler, authenticated_only)

    def set_default_arg(
        self,
        arg_name,
        value: Optional[Any] = None,
        factory: Optional[Callable] = None
    ) -> None:
        self._default_realm.set_default_arg(arg_name, value, factory)

    def add_rpc_routes(self, routes):
        self._default_realm.add_rpc_routes(routes)

    def add_topic_routes(self, routes):
        self._default_realm.add_topic_routes(routes)

    async def _start_session_state_handlers(self, handlers, session):
        async with self._async_support.launch_task_group() as start_tasks:
            for handler in handlers:
                args = session.realm.args_for_realm_level_handler(
                    handler,
                    session=session
                )
                state_iter = handler(*args)
                await start_tasks.spawn(state_iter.__anext__)
                self._session_state_exits[session].add(state_iter)

    async def default_protocol_subscribe_handler(
            self,
            request: WAMPSubscribeRequest,
            session: WAMPSession
    ):
        sub_id = await session.register_subscription(
            request.topic
        )
        subscribe_unsubscribe_iter = session.realm.handle_subscription(request.topic, session)
        await subscribe_unsubscribe_iter.__anext__()
        self._subscription_exits[session][sub_id] = subscribe_unsubscribe_iter
        await session.mark_subscribed(request, sub_id)

    async def default_protocol_unsubscribe_handler(
            self,
            request: WAMPUnsubscribeRequest,
            session: WAMPSession
    ):
        subscribe_unsubscribe_iter = self._subscription_exits[session].pop(
            request.subscription
        )
        if subscribe_unsubscribe_iter:
            try:
                await subscribe_unsubscribe_iter.__anext__()
            except StopAsyncIteration:
                pass
            else:
                "TODO: raise exception because there should only be a single yield"
        try:
            await session.unregister_subscription(request.subscription)
        except NoSuchSubscription:
            await session.send_raw(
                unsubscribe_error_response_msg(
                    request,
                    'wamp.error.no_such_subscription'
                )
            )

    # Support for various web servers/frameworks

    def aiohttp_websocket_handler(self):
        from serverwamp.adapters.aiohttp import connection_for_aiohttp_request

        async def handle_aiohttp_request(request):
            connection = await connection_for_aiohttp_request(request)

            # Have to shield as aiohttp will cancel us prior to cleanup after
            # disconnect.
            await self._async_support.shield(
                self.handle_connection, connection
            )

        return handle_aiohttp_request

    def asgi_application(
        self,
        paths: Optional[Collection[str]] = None
    ):
        from serverwamp.adapters.asgi import (
            handle_asgi_path_not_found,
            connection_for_asgi_invocation
        )
        """Returns an ASGI application callable that serves WAMP on the given
        paths. Other paths will return a 404. If paths is omitted, any path
        requested by the user agent will serve WAMP sessions.
        """
        async def application_callable(
            scope: Mapping,
            receive: Callable[[], Awaitable[Mapping]],
            send: Callable[[Mapping], Awaitable]
        ) -> None:
            if paths and scope['path'] not in paths:
                return await handle_asgi_path_not_found(scope, receive, send)
            connection = await connection_for_asgi_invocation(scope, receive,
                                                              send)
            await self.handle_connection(connection)
        return application_callable

    def legacy_asgi_application(
        self,
        paths: Optional[Collection[str]] = None
    ):
        from serverwamp.adapters.asgi import (
            handle_asgi_path_not_found,
            connection_for_asgi_invocation
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
                if paths and scope['path'] not in paths:
                    return (
                        await handle_asgi_path_not_found(scope, receive, send)
                    )
                connection = await connection_for_asgi_invocation(scope,
                                                                  receive, send)
                await self.handle_connection(connection)
            return application_handler

        return application_callable


def verify_cra_response(response: CRAResponse, secret: Union[bytes, bytearray]):
    hmac = HMAC(key=secret, msg=response.challenge.encode('utf-8'),
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
    invocation = session.realm.handle_rpc_call(rpc_request=rpc_request)
    if isinstance(invocation, AsyncIterator):
        while True:
            try:
                result = await invocation.__anext__()
            except StopAsyncIteration:
                break
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

    result = await invocation
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
