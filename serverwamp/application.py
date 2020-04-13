from dataclasses import dataclass
from hashlib import sha256
from hmac import HMAC
from typing import (Any, Awaitable, Callable, Iterable, MutableMapping,
                    Optional, Union, Type, Mapping, Collection, AsyncIterator)

from serverwamp.adapters.async_base import AsyncSupport
from serverwamp.protocol import (WAMPGoodbyeRequest, WAMPHelloRequest,
                                 WAMPMsgParseError, WAMPRPCRequest,
                                 WAMPSubscribeRequest, WAMPUnsubscribeRequest,
                                 wamp_request_from_msg, WAMPRequest,
                                 unsubscribe_error_response_msg,
                                 call_result_response_msg,
                                 call_error_response_msg)
from serverwamp.rpc import (RPCRouter, RPCRequest, RPCErrorResult,
                            RPCProgressReport, RPCHandler)
from serverwamp.session import NoSuchSubscription, WAMPSession

ProtocolRequestHandlerMap = Mapping[
    Type[WAMPRequest],
    Callable[[WAMPRequest, WAMPSession], Awaitable[None]]
]


class Realm:
    def __init__(
        self,
        uri: Optional[str] = None,
        custom_auth_handler: Optional[
            Callable[[str, WAMPSession], Awaitable[Any]]
        ] = None,
        transport_auth_handler: Optional[
            Callable[[WAMPSession], Awaitable[Any]]
        ] = None,
        cra_identity_provider: Optional[
            Callable[[WAMPSession], Awaitable[Any]]
        ] = None,
        cra_requirement_provider: Optional[
            Callable[[str, str], Awaitable[CRAAuthRequirement]]
        ] = None,
        ticket_auth_handler: Optional[
            Callable[..., Awaitable[Any]]
        ] = None,
        session_handler: Optional[
            Callable[[WAMPSession], Awaitable[None]]
        ] = None
    ):
        self._router = RPCRouter()
        if self.rpc_handler:
            self._handle_rpc_call = rpc_handler
        else:
            self._handle_rpc_call = self._router.handle_rpc_call

    async def default_auth_handler(self, session):
        realm = session.realm
        if realm.transport_auth_handler:
            identity = await realm.transport_auth_handler(session)
            if identity:
                await session.mark_authenticated(identity)
                return

        if 'wampcra' in session.auth_methods and realm.cra_requirement_provider:
            cra_requirement = await (
                realm.cra_requirement_provider(
                    realm.uri,
                    session.auth_id
                )
            )
            response = await session.request_cra_auth(
                session.auth_id,
                cra_requirement.auth_role,
                cra_requirement.auth_provider
            )
            if verify_cra_response(response, cra_requirement.secret):
                identity = await realm.cra_identity_provider(session)
                if identity:
                    await session.mark_authenticated(identity)
                    return
        elif 'ticket' in session.auth_methods and realm.ticket_auth_handler:
            ticket = await session.request_ticket_auth()
            identity = await realm.ticket_auth_handler(session, ticket)
            if identity:
                await session.mark_authenticated(identity)
                return

        await session.abort(uri='wamp.error.authentication_failed',
                            message='Authentication failed.')

    def set_default_rpc_arg(
        self,
        arg_name,
        value: Optional[Any] = None,
        factory: Optional[Callable] = None,
        realms: Optional[Iterable[str]] = None
    ) -> None:
        self._router.set_default_arg(arg_name, value, factory, realms)

    def add_rpc_routes(self, routes, realms=None):
        self._router.add_routes(routes, realms)


def verify_cra_response(response: CRAResponse, secret: Union[bytes, bytearray]):
    hmac = HMAC(key=secret, msg=response.challenge.encode('utf-8'),
                digestmod=sha256)
    return response.signature.encode('utf-8') == hmac.digest()


async def default_protocol_subscribe_handler(
    request: WAMPSubscribeRequest,
    session: WAMPSession
):
    sub_id = await session.register_subscription(request.topic)
    await session.mark_subscribed(request, sub_id)


async def default_protocol_unsubscribe_handler(
    request: WAMPUnsubscribeRequest,
    session: WAMPSession
):
    try:
        await request.session.unregister_subscription(request.subscription)
    except NoSuchSubscription:
        await session.send_raw(
            unsubscribe_error_response_msg(
                request,
                'wamp.error.no_such_subscription'
            )
        )


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
        self._realms: MutableMapping[str, ApplicationRealm] = {}

        self._default_realm = ApplicationRealm() if allow_default_realm else None

        self._protocol_request_handlers = {
            WAMPGoodbyeRequest: default_protocol_goodbye_handler,
            WAMPRPCRequest: default_protocol_rpc_handler,
            WAMPSubscribeRequest: default_protocol_subscribe_handler,
            WAMPUnsubscribeRequest: default_protocol_unsubscribe_handler
        }
        if protocol_request_handlers:
            self._protocol_request_handlers.update(protocol_request_handlers)

        self._synchronize_requests = synchronize_requests

    def create_realm(self, uri):
        realm = Realm(uri)
        self._realms[realm.uri] = realm

    async def default_session_handler(
        self,
        session: WAMPSession,
    ):
        connection = session.connection
        realm = session.realm
        # Try auth handlers if there are any.
        if realm.custom_auth_handler:
            await realm.custom_auth_handler(session)
        else:
            await self.default_auth_handler(session)

        # Technically, once the session is authenticated, order is not
        # important to the WAMP protocol itself; messages expecting responses
        # have identifiers for referring back to them. Ordering may still be
        # important to the app, however.
        if self._synchronize_requests:
            async for msg in connection.iterate_msgs():
                try:
                    request = wamp_request_from_msg(msg, None)
                except WAMPMsgParseError:
                    await connection.abort('wamp.error.protocol_error',
                                           'Parse error.')
                    return
                handler = self._protocol_request_handlers[type(msg)]
                await handler(request, session)
            return

        async for msg in connection.iterate_msgs():
            try:
                request = wamp_request_from_msg(msg, None)
            except WAMPMsgParseError:
                await connection.abort('wamp.error.protocol_error',
                                       'Parse error.')
                return
            handler = self._protocol_request_handlers[type(request)]
            session.spawn_task(handler, request, session)

    def set_default_rpc_arg(
        self,
        arg_name,
        value: Optional[Any] = None,
        factory: Optional[Callable] = None,
        realms: Optional[Iterable[str]] = None
    ) -> None:
        self._router.set_default_arg(arg_name, value, factory, realms)

    def add_rpc_routes(self, routes, realms=None):
        self._router.add_routes(routes, realms)

    async def handle_connection(self, connection):
        msgs = connection.iterate_msgs()

        # They say hello or we show them the door.  TODO: timeout?
        async for msg in msgs:
            try:
                request = wamp_request_from_msg(msg, None)
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
            if realm.session_handler:
                await realm.session_handler(session)
            else:
                await self.default_session_handler(session)
                try:
                    request = wamp_request_from_msg(msg, session)
                except WAMPMsgParseError:
                    await connection.abort('wamp.error.protocol_error',
                                           'Parse error.')
                    return

    async def default_protocol_rpc_handler(self, request, session):
        partition_route = (
            request.options['rkey']
            if request.options.get('runmode') == 'partition'
            else None
        )
        rpc_request = RPCRequest(
            session=session,
            uri=request.uri,
            args=request.args,
            kwargs=request.kwargs,
            timeout=request.options.get('timeout', 0),
            disclose_caller=request.options.get('disclose_me', False),
            receive_progress=request.options.get('receive_progress', False),
            partition_route=partition_route
        )
        invocation = self._handle_rpc_call(rpc_request=rpc_request)
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
                    call_result_response_msg(request, result.args,
                                             result.kwargs)
                )
                return

        result = await invocation
        yield result

    # Support for various web servers/frameworks

    def aiohttp_websocket_handler(self):
        from serverwamp.adapters.aiohttp import connection_for_aiohttp_request

        async def handle_aiohttp_request(request):
            connection = connection_for_aiohttp_request(request)
            await self.handle_connection(connection)

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
            connection = connection_for_asgi_invocation(scope, receive, send)
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
                connection = connection_for_asgi_invocation(scope, receive,
                                                            send)
                await self.handle_connection(connection)
            return application_handler

        return application_callable


@dataclass
class CRAAuthRequirement:
    secret: bytes
    auth_role: str
    auth_provider: str


@dataclass
class CRAResponse:
    signature: str
    challenge: str





async def default_protocol_goodbye_handler(
    request: WAMPGoodbyeRequest,
    session: WAMPSession
):
    await session.close()
