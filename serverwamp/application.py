from dataclasses import dataclass
from hashlib import sha256
from hmac import HMAC
from typing import (Any, Awaitable, Callable, Iterable, MutableMapping,
                    Optional, Union, Type, Mapping, Collection)

from serverwamp.adapters.async_base import AsyncSupport
from serverwamp.protocol import (WAMPGoodbyeRequest, WAMPHelloRequest,
                                 WAMPMsgParseError, WAMPRPCRequest,
                                 WAMPSubscribeRequest, WAMPUnsubscribeRequest,
                                 wamp_request_from_msg)
from serverwamp.rpc import Router
from serverwamp.session import NoSuchSubscription, WAMPSession


class WAMPApplication:
    def __init__(
        self,
        async_support: Optional[Type[AsyncSupport]] = None,
        synchronize_requests: bool = False
    ):
        if async_support:
            self._async_support = async_support
        else:
            from serverwamp.adapters.asyncio import AsyncioAsyncSupport
            self._async_support = AsyncioAsyncSupport
        self._realms: MutableMapping[str, ApplicationRealm] = {}
        self._router = Router()
        self._request_handlers = {
            WAMPGoodbyeRequest: WAMPApplication.default_goodbye_handler,
            WAMPRPCRequest: WAMPApplication.default_rpc_handler,
            WAMPSubscribeRequest: WAMPApplication.default_subscribe_handler,
            WAMPUnsubscribeRequest: WAMPApplication.default_unsubscribe_handler
        }
        self._synchronize_requests = synchronize_requests

    async def default_session_handler(
        self,
        session: WAMPSession,
    ):
        realm = session.realm
        # Try auth handlers if there are any.
        if realm.custom_auth_handler:
            await realm.custom_auth_handler(session)
        else:
            await self.default_auth_handler(session)

        if self._synchronize_requests:
            async for request in session.iterate_requests():
                handler = self._request_handlers[type(request)]
                await handler(request)
        else:
            async for request in session.iterate_requests():
                handler = self._request_handlers[type(request)]
                session.spawn_task(handler, request)

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

    async def default_auth_handler(self, session):
        realm = self._realms[session.realm]
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
            await session.mark_authenticated(identity)
            return

        await session.abort(uri='wamp.error.authentication_failed',
                            message='Authentication failed.')

    async def default_rpc_handler(self, request):
        await self._router.handle_rpc_call(rpc_request=request)

    async def default_subscribe_handler(self, request):
        sub_id = await request.session.register_subscription(request.uri)
        await request.session.mark_subscribed(request, sub_id)

    async def default_unsubscribe_handler(self, request):
        try:
            await request.session.unregister_subscription(request.subscription)
        except NoSuchSubscription:
            await request.session.subscription

    async def default_goodbye_handler(self, request):
        await request.session.close()

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

    # Support for various web servers/frameworks

    async def aiohttp_websocket_handler(self):
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


@dataclass
class ApplicationRealm:
    uri: str
    custom_auth_handler: Callable[[str, WAMPSession], Awaitable[Any]]
    transport_auth_handler: Callable[[WAMPSession], Awaitable[Any]]
    cra_identity_provider: Callable[[WAMPSession], Awaitable[Any]]
    cra_requirement_provider: Callable[[str, str], Awaitable[CRAAuthRequirement]]
    ticket_auth_handler: Callable[..., Awaitable[Any]]
    session_handler: Callable[[WAMPSession], Awaitable[None]]


def verify_cra_response(response: CRAResponse, secret: Union[bytes, bytearray]):
    hmac = HMAC(key=secret, msg=response.challenge.encode('utf-8'),
                digestmod=sha256)
    return response.signature.encode('utf-8') == hmac.digest()
