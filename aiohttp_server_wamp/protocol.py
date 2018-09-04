import asyncio
import logging
from collections import Mapping, Sequence
from enum import IntEnum, unique
from json import dumps as serialize
from json import loads as deserialize
from random import randint

import attr

logger = logging.getLogger(__name__)


@unique
class WAMPMsgType(IntEnum):
    HELLO = 1
    WELCOME = 2
    ABORT = 3

    ERROR = 8

    CALL = 48
    CALL_RESULT = 50

    SUBSCRIBE = 32
    SUBSCRIBED = 33

    UNSUBSCRIBE = 34
    UNSUBSCRIBED = 35

    PUBLISH = 16
    PUBLISHED = 17
    EVENT = 36


class WAMPProtocol:
    def __init__(self, transport, *args, open_handler=None, rpc_handler=None,
                 subscribe_handler=None, unsubscribe_handler=None, loop=None,
                 **kwargs):
        self.session_id = randint(1, 9007199254740992)
        self.transport = transport
        self.loop = loop or asyncio.get_event_loop()

        self._open_handler = open_handler
        self._subscribe_handler = subscribe_handler
        self._unsubscribe_handler = unsubscribe_handler
        self._rpc_handler = rpc_handler

        super(WAMPProtocol, self).__init__(*args, **kwargs)

    def do_unimplemented(self, msg_type, request_id):
        error_msg = (WAMPMsgType.ERROR, request_id, {},
                     'wamp.error.not_implemented')
        self.transport.schedule_msg(serialize(error_msg))

    async def do_protocol_violation(self, msg=None):
        if msg:
            details = {'message': msg}
        else:
            details = {}

        error_msg = (WAMPMsgType.ABORT, details,
                     'wamp.error.protocol_violation')
        await self.transport.schedule_msg(serialize(error_msg))
        await self.transport.close()

    def do_welcome(self):
        welcome = (
            WAMPMsgType.WELCOME,
            int(self.session_id),
            {
                'roles': {'broker': {}, 'dealer': {}}
            }
        )
        self.transport.schedule_msg(serialize(welcome))

    async def rpc_call(self, data):
        logger.debug(data)

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

        if not isinstance(request_id, str) or not isinstance(uri, str):
            raise Exception()

        try:
            request = WAMPRPCRequest(
                self.session_id,
                request_id,
                remote=self.transport.remote,
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
                "wamp.error.exception_during_rpc_call",
                str(e)
            )

        self.transport.schedule_msg(serialize(result_msg))

    async def pubsub_action(self, data):
        logger.debug(data)
        action = data[0]
        topic_uri = data[1]

        if not (isinstance(action, int) and isinstance(topic_uri, str)):
            raise Exception()

        if action == WAMPMsgType.SUBSCRIBE and len(data) == 2:
            self._subscribe_handler(topic_uri)
        elif action == WAMPMsgType.UNSUBSCRIBE and len(data) == 2:
            self._unsubscribe_handler(topic_uri)

    def on_open(self):
        self._open_handler()

    async def handle_msg(self, message):
        data = deserialize(message)

        if not isinstance(data, list):
            raise Exception('incoming data is no list')

        msg_type = data[0]
        if msg_type == WAMPMsgType.HELLO:
            self.do_welcome()
        elif msg_type == WAMPMsgType.CALL and len(data) >= 3:
            await self.rpc_call(data)
        elif msg_type in (WAMPMsgType.SUBSCRIBE, WAMPMsgType.UNSUBSCRIBE):
            await self.pubsub_action(data)
        elif msg_type in (WAMPMsgType.PUBLISH, WAMPMsgType.PUBLISHED,
                          WAMPMsgType.EVENT):
            self.do_unimplemented(msg_type, data[1])
        else:
            await self.do_protocol_violation("Unknown WAMP message type.")


@attr.s(frozen=True, slots=True)
class WAMPRequest:
    session_id: int = attr.ib()
    request_id: int = attr.ib()
    remote: str = attr.ib()


@attr.s(frozen=True, slots=True)
class WAMPSubscribeRequest(WAMPRequest):
    options: Mapping = attr.ib()
    uri: str = attr.ib()


@attr.s(frozen=True, slots=True)
class WAMPSubscribeResponse(WAMPRequest):
    request: WAMPSubscribeRequest = attr.ib()
    subscription: int = attr.ib()


@attr.s(frozen=True, slots=True)
class WAMPSubscribeErrorResponse:
    request: WAMPSubscribeRequest = attr.ib()
    uri: str = attr.ib()
    details: Mapping = attr.ib(factory=dict)


@attr.s(frozen=True, slots=True)
class WAMPUnsubscribeRequest(WAMPRequest):
    options: Mapping = attr.ib()
    uri: str = attr.ib()


@attr.s(frozen=True, slots=True)
class WAMPUnsubscribeResponse:
    request: WAMPUnsubscribeRequest = attr.ib()


@attr.s(frozen=True, slots=True)
class WAMPUnsubscribeErrorResponse:
    request: WAMPUnsubscribeRequest = attr.ib()
    uri: str = attr.ib()
    details: Mapping = attr.ib(factory=dict)


@attr.s(frozen=True, slots=True)
class WAMPEvent:
    subscription: int = attr.ib()
    publication: int = attr.ib()
    details: Mapping = attr.ib(factory=dict)
    args: Sequence = attr.ib(default=())
    kwargs: Mapping = attr.ib(factory=dict)


@attr.s(frozen=True, slots=True)
class WAMPRPCRequest(WAMPRequest):
    options: Mapping = attr.ib()
    uri: str = attr.ib()
    args: Sequence = attr.ib(default=())
    kwargs: Mapping = attr.ib(factory=dict)


@attr.s(frozen=True, slots=True)
class WAMPRPCResponse:
    request: WAMPRPCRequest = attr.ib()
    details: Mapping = attr.ib()
    args: Sequence = attr.ib(default=())
    kwargs: Mapping = attr.ib(factory=dict)


@attr.s(frozen=True, slots=True)
class WAMPRPCErrorResponse(WAMPRPCResponse):
    request: WAMPRPCRequest = attr.ib()
    details: Mapping = attr.ib()
    uri: str = attr.ib()
    args: Sequence = attr.ib(default=())
    kwargs: Mapping = attr.ib(factory=dict)
