import asyncio
import logging
from collections import Mapping, Sequence
from dataclasses import dataclass, field
from enum import IntEnum, unique
from json import dumps as serialize
from json import loads as deserialize
from random import randint
from typing import Any, Awaitable, Callable, Iterable, Optional

from serverwamp.helpers import format_sockaddr

logger = logging.getLogger(__name__)


@unique
class WAMPMsgType(IntEnum):
    HELLO = 1
    WELCOME = 2
    ABORT = 3

    ERROR = 8

    CALL = 48
    CALL_RESULT = 50
    INVOCATION = 68

    SUBSCRIBE = 32
    SUBSCRIBED = 33

    UNSUBSCRIBE = 34
    UNSUBSCRIBED = 35

    PUBLISH = 16
    PUBLISHED = 17
    EVENT = 36


def generate_global_id():
    """Returns an integer that can be used for globally scoped identifiers in
    WAMP communications. Per the WAMP spec, these are random."""
    return randint(1, 9007199254740992)


class AuthenticationFailure(Exception):
    def __init__(self, reason: str = None):
        self.reason = reason


class WAMPProtocol:
    def __init__(
        self,
        transport: Any,
        *args,
        open_handler: Optional[Callable] = None,
        rpc_handler: Optional[Callable] = None,
        subscribe_handler: Optional[Callable] = None,
        unsubscribe_handler: Optional[Callable] = None,
        loop: Optional[Any] = None,
        agent_name: Optional[str] = None,
        websocket_open_handler: Optional[Callable] = None,
        identity_authenticated_handler: Optional[Callable] = None,
        transport_authenticator: Optional[Callable[..., Awaitable[Any]]] = None,
        **kwargs
    ) -> None:
        self.session = WAMPSession(
            session_id=generate_global_id(),
            remote=transport.remote
        )
        self.transport = transport
        self.loop = loop or asyncio.get_event_loop()

        self._transport_authenticator = transport_authenticator
        self._open_handler = open_handler
        self._subscribe_handler = subscribe_handler
        self._unsubscribe_handler = unsubscribe_handler
        self._rpc_handler = rpc_handler
        self._identity_authenticated_handler = identity_authenticated_handler
        self._websocket_open_handler = websocket_open_handler

        self.agent_name = agent_name or 'aiohttp-server-wamp'

    def do_unimplemented(self, request_id):
        self.send_msg((
            WAMPMsgType.ERROR,
            request_id,
            {},
            'wamp.error.not_implemented'
        ))

    async def authenticate(self):
        failures = []
        identity = None
        if self._transport_authenticator:
            try:
                identity = await self._transport_authenticator(self.transport)
            except AuthenticationFailure as af:
                failures.append(af)
        # More authenticators can be checked here.

        if failures:
            message = ' '.join([af.reason for af in failures if af.reason])
            await self.do_abort(
                'wamp.error.not_authorized',
                message=message or None
            )
            return

        if self._identity_authenticated_handler:
            self._identity_authenticated_handler(identity)
        self.do_welcome()
        if self._open_handler:
            self._open_handler(self.session)

    async def do_protocol_violation(self, message=None):
        await self.do_abort('wamp.error.protocol_violation', message)

    def do_welcome(self):
        self.send_msg((
            WAMPMsgType.WELCOME,
            self.session.session_id,
            {
                'roles': {'broker': {}, 'dealer': {}},
                'agent': self.agent_name
            }
        ))

    async def do_abort(self, reason, message=None):
        details = {}
        if message:
            details['message'] = message
        self.send_msg((WAMPMsgType.ABORT, reason,  details))
        await self.transport.close()

    def do_unauthorized(self, data):
        msg_type = data[0]
        request_id = data[1]
        self.send_msg((msg_type, request_id, {}, "wamp.error.not_authorized"))

    def publish_event(self, subscription, event):
        msg = [
            WAMPMsgType.EVENT,
            subscription,
            event.publication,
            {}
        ]
        if event.kwargs:
            msg.append(event.args)
            msg.append(event.kwargs)
        elif event.args:
            msg.append(event.args)
        self.send_msg(msg)

    async def recv_rpc_call(self, data):
        request_id = data[1]
        uri = data[2]
        if len(data) > 3:
            args = data[3]
        else:
            args = ()
        if len(data) > 4:
            kwargs = data[4]
        else:
            kwargs = {}

        if not isinstance(request_id, int) or not isinstance(uri, str):
            raise Exception()

        try:
            request = WAMPRPCRequest(
                self.session,
                request_id,
                uri=uri,
                options={},
                args=args,
                kwargs=kwargs
            )
            result = self._rpc_handler(request)
            if isinstance(result, WAMPRPCErrorResponse):
                result_msg = (
                    WAMPMsgType.ERROR,
                    WAMPMsgType.CALL,
                    request_id,
                    {},
                    result.uri,
                    result.args,
                    result.kwargs
                )
            else:
                result_msg = (WAMPMsgType.CALL_RESULT, request_id, result)
        except Exception as e:
            result_msg = (
                WAMPMsgType.ERROR,
                WAMPMsgType.CALL,
                request_id,
                {},
                'wamp.error.exception_during_rpc_call',
                str(e)
            )

        self.send_msg(result_msg)

    async def recv_subscribe(self, data):
        request_id = data[1]
        options = data[2]
        uri = data[3]

        request = WAMPSubscribeRequest(
            self.session,
            request_id,
            options=options,
            uri=uri
        )

        try:
            result = self._subscribe_handler(request)
            if isinstance(result, WAMPSubscribeErrorResponse):
                result_msg = (
                    WAMPMsgType.ERROR,
                    WAMPMsgType.SUBSCRIBE,
                    request_id,
                    result.details,
                    result.uri
                )
            else:
                result_msg = (
                    WAMPMsgType.SUBSCRIBED,
                    request_id,
                    result.subscription
                )
        except Exception as e:
            result_msg = (
                WAMPMsgType.ERROR,
                WAMPMsgType.SUBSCRIBE,
                request_id,
                {},
                "wamp.error.exception_during_rpc_call",
                str(e)
            )
        self.send_msg(result_msg)

    async def recv_unsubscribe(self, data):
        request_id = data[1]
        subscription = data[2]

        request = WAMPUnsubscribeRequest(
            self.session,
            request_id,
            subscription=subscription
        )

        try:
            result = self._unsubscribe_handler(request)
            if isinstance(result, WAMPUnsubscribeErrorResponse):
                result_msg = (
                    WAMPMsgType.ERROR,
                    WAMPMsgType.UNSUBSCRIBE,
                    request_id,
                    result.details,
                    result.uri
                )
            else:
                result_msg = (WAMPMsgType.UNSUBSCRIBED, request_id)
        except Exception as e:
            result_msg = (
                WAMPMsgType.ERROR,
                WAMPMsgType.SUBSCRIBE,
                request_id,
                {},
                "wamp.error.exception_during_rpc_call",
                str(e)
            )
        self.send_msg(result_msg)

    async def handle_msg(self, message):
        data = deserialize(message)

        if not isinstance(data, list):
            raise Exception('incoming data is no list')

        msg_type = data[0]
        if msg_type == WAMPMsgType.HELLO:
            await self.authenticate()
        elif msg_type == WAMPMsgType.CALL:
            await self.recv_rpc_call(data)
        elif msg_type == WAMPMsgType.SUBSCRIBE:
            await self.recv_subscribe(data)
        elif msg_type == WAMPMsgType.UNSUBSCRIBE:
            await self.recv_unsubscribe(data)
        elif msg_type in (WAMPMsgType.EVENT, WAMPMsgType.INVOCATION):
            await self.do_unauthorized(data)
        elif msg_type in (WAMPMsgType.PUBLISH, WAMPMsgType.PUBLISHED):
            self.do_unimplemented(msg_type)
        else:
            await self.do_protocol_violation("Unknown WAMP message type.")

    async def handle_websocket_open(self) -> None:
        if self._websocket_open_handler:
            self._websocket_open_handler()

    def send_msg(self, msg: Iterable):
        self.transport.send_msg_soon(serialize(msg))


@dataclass(frozen=True)
class WAMPSession:
    session_id: int
    remote: Optional[str] = None


@dataclass(frozen=True)
class WAMPRequest:
    session: WAMPSession
    request_id: int


@dataclass(frozen=True)
class WAMPSubscribeRequest(WAMPRequest):
    options: Mapping
    uri: str


@dataclass(frozen=True)
class WAMPSubscribeResponse(WAMPRequest):
    request: WAMPSubscribeRequest
    subscription: int


@dataclass(frozen=True)
class WAMPSubscribeErrorResponse:
    request: WAMPSubscribeRequest
    uri: str
    details: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPUnsubscribeRequest(WAMPRequest):
    subscription: int


@dataclass(frozen=True)
class WAMPUnsubscribeErrorResponse:
    request: WAMPUnsubscribeRequest
    uri: str
    details: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPEvent:
    publication: int = field(default_factory=generate_global_id)
    details: Mapping = field(default_factory=dict)
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPRPCRequest(WAMPRequest):
    options: Mapping
    uri: str
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPRPCResponse:
    request: WAMPRPCRequest
    details: Mapping = field(default_factory=dict)
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPRPCErrorResponse:
    request: WAMPRPCRequest
    uri: str
    details: Mapping = field(default_factory=dict)
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)
