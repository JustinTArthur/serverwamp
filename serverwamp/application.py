from dataclasses import dataclass
from hashlib import sha256
from hmac import HMAC
from typing import (Any, Awaitable, Callable, Iterable, MutableMapping,
                    Optional, Union)

from serverwamp.protocol import (WAMPGoodbyeRequest, WAMPHelloRequest,
                                 WAMPMsgParseError, WAMPRPCRequest,
                                 WAMPSubscribeRequest, WAMPUnsubscribeRequest,
                                 wamp_request_from_msg)
from serverwamp.rpc import Router
from serverwamp.session import NoSuchSubscription, WAMPSession


class WAMPApplication:
    def __init__(self):
        self._realms: MutableMapping[str, ApplicationRealm] = {}
        self._router = Router()
        self._request_handlers = {
            WAMPGoodbyeRequest: WAMPApplication.default_goodbye_handler,
            WAMPRPCRequest: WAMPApplication.default_rpc_handler,
            WAMPSubscribeRequest: WAMPApplication.default_subscribe_handler,
            WAMPUnsubscribeRequest: WAMPApplication.default_unsubscribe_handler
        }

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
        async for request in session.iterate_requests():
            self._request_handlers[type(request)](request)

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

        # They say hello or we show them the door.
        async for msg in msgs:
            try:
                # TODO timeout?
                request = wamp_request_from_msg(msg, None)
            except WAMPMsgParseError:
                await connection.abort('wamp.error.protocol_error',
                                       'Parse error.')
                return
            continue
        if not isinstance(request, WAMPHelloRequest):
            await connection.abort('wamp.error.protocol_error',
                                   'Unexpected request.')
            return

        if request.realm_uri not in self._realms:
            """TODO abort no such realm or we allow any realm."""

        session = WAMPSession(
            connection,
            request.realm_uri,
            auth_id=request.details.get('authid', None),
            auth_methods=request.details.get('authmethods', ())
        )
        async for msg in msgs:
            try:
                request = wamp_request_from_msg(msg, session)
            except WAMPMsgParseError:
                """TODO"""


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


def verify_cra_response(response: CRAResponse, secret: Union[bytes, bytearray]):
    hmac = HMAC(key=secret, msg=response.challenge.encode('utf-8'),
                digestmod=sha256)
    return response.signature.encode('utf-8') == hmac.digest()
