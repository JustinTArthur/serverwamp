import asyncio
import logging
from abc import ABC, abstractmethod
from collections import Sequence
from dataclasses import InitVar, dataclass, field
from enum import IntEnum, unique
from json import dumps as serialize
from json import loads as deserialize
from random import randint
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

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


class Transport(ABC):
    @property
    def cookies(self) -> Optional[Mapping[str, str]]:
        return None

    @property
    def remote(self):
        return None

    @abstractmethod
    def send_msg_soon(self, msg: str) -> None:
        """Send a serialized message to the underlying transport at some point
        soon. Returns immediately without awaiting any kind of send
        confirmation."""
        pass

    @abstractmethod
    async def send_msg(self, msg: str) -> None:
        """Send a message to the underlying transport immediately, and block
        until the underlying send is complete.
        """
        pass

    @abstractmethod
    async def close(self):
        """Close the underlying transport as soon as any scheduled tasks
        are complete."""
        pass


class WAMPProtocol:
    def __init__(
        self,
        transport: Transport,
        *args,
        open_handler: Optional[Callable] = None,
        rpc_handler: Optional[Callable] = None,
        subscribe_handler: Optional[Callable] = None,
        unsubscribe_handler: Optional[Callable] = None,
        loop: Optional[Any] = None,
        agent_name: Optional[str] = None,
        websocket_open_handler: Optional[Callable] = None,
        identity_authenticated_handler: Optional[Callable] = None,
        transport_authenticator: Optional[Callable[[Transport, str], Awaitable[Any]]] = None,
        **kwargs
    ) -> None:
        self.session = WAMPSession(
            session_id=generate_global_id(),
            remote=transport.remote,
            protocol=self
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

        self._received_hello = False

    def do_unimplemented(self, request_id):
        self.send_msg((
            WAMPMsgType.ERROR,
            request_id,
            {},
            'wamp.error.not_implemented'
        ))

    def attach_to_realm(self, realm: str):
        self.session.realm = realm

    async def authenticate(self):
        failures = []
        identity = None
        if self._transport_authenticator:
            try:
                identity = await self._transport_authenticator(
                    self.transport,
                    realm=self.session.realm
                )
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

        self.session.identity = identity
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

    def do_event(
        self,
        subscription_id: int,
        publication_id: Optional[int] = None,
        args: Optional[Iterable] = None,
        kwargs: Optional[Mapping] = None,
        publisher_id: Optional[int] = None,
        trust_level: Optional[int] = None
    ) -> int:
        publication_id = publication_id or generate_global_id()
        details = {}
        if publisher_id:
            details['publisher'] = publisher_id
        if trust_level:
            details['trustlevel'] = trust_level
        msg = [
            WAMPMsgType.EVENT,
            subscription_id,
            publication_id,
            details,
        ]
        if kwargs is not None:
            msg.append(args or ())
            msg.append(kwargs)
        elif args is not None:
            msg.append(args)
        self.send_msg(msg)
        return publication_id

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

    async def recv_hello(self, data):
        if self._received_hello:
            await self.do_protocol_violation(
                'Only one hello allowed per session.'
            )
            return

        self._received_hello = True
        realm = data[1]
        self.attach_to_realm(realm)
        await self.authenticate()

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

        await self.session.add_subscription(topic=uri)
        request = WAMPSubscribeRequest(
            self.session,
            request_id,
            options=options,
            uri=uri
        )

        try:
            result = await self._subscribe_handler(request)
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

        await self.session.remove_subscription(subscription)
        request = WAMPUnsubscribeRequest(
            self.session,
            request_id,
            subscription=subscription
        )

        try:
            result = await self._unsubscribe_handler(request)
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
            await self.recv_hello(data)
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


@dataclass()
class WAMPSession:
    session_id: int
    realm: Optional[str] = None
    remote: Optional[str] = None
    protocol: InitVar[Optional[WAMPProtocol]] = None
    identity: Optional[Any] = None

    def __post_init__(self, protocol: Optional[WAMPProtocol]):
        self._protocol = protocol
        self._subscriptions = {}
        self._subscriptions_ids = {}

    def subscription_id_for_topic(self, topic):
        return hash(topic) & 0xFFFFFFFF

    async def add_subscription(self, topic):
        subscription_id = self.subscription_id_for_topic(topic)
        self._subscriptions[topic] = subscription_id
        self._subscriptions_ids[subscription_id] = topic

    async def remove_subscription(self, subscription_id):
        topic = self._subscriptions_ids.pop(subscription_id)
        if topic:
            self._subscriptions.pop(subscription_id)

    async def send_event(self, topic, *args, **kwargs):
        subscription_id = self._subscriptions.get(topic)
        if not subscription_id:
            return False

        self._protocol.do_event(
            subscription_id,
            args=args,
            kwargs=kwargs
        )
        return True


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
