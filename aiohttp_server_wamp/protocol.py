import asyncio
import logging
from enum import IntEnum, unique
from json import dumps as serialize
from json import loads as deserialize
from random import randint

logger = logging.getLogger(__name__)


@unique
class WAMPMsgType(IntEnum):
    HELLO = 1
    WELCOME = 2
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

    def do_welcome(self):
        welcome = (
            WAMPMsgType.WELCOME,
            int(self.session_id),
            {
                'roles': {'broker': {}, 'dealer': {}}
            }
        )
        self.loop.create_task(self.transport.send_str(serialize(welcome)))

    async def rpc_call(self, data):
        logger.debug(data)

        call_id = data[1]
        uri = data[2]
        if len(data) > 3:
            args = data[3]
        else:
            args = ()
        if len(data) > 4:
            kwargs = data[4]
        else:
            kwargs = {}

        if not isinstance(call_id, str) or not isinstance(uri, str):
            raise Exception()

        try:
            result = self._rpc_handler(uri, call_id, args, kwargs)
            result_msg = (WAMPMsgType.CALL_RESULT, call_id, result)
        except Exception as e:
            result_msg = (
                WAMPMsgType.ERROR,
                WAMPMsgType.CALL,
                call_id,
                {},
                "wamp.error.exception_during_rpc_call",
                str(e)
            )

        self.transport.send_str(serialize(result_msg))

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
        logger.debug("open!")
        self._open_handler()

    async def handle_msg(self, message):
        data = deserialize(message)

        if not isinstance(data, list):
            raise Exception('incoming data is no list')

        msg_type = data[0]
        if msg_type == WAMPMsgType.HELLO:
            return self.do_welcome()
        elif msg_type == WAMPMsgType.CALL and len(data) >= 3:
            return await self.rpc_call(data)
        elif msg_type in (WAMPMsgType.SUBSCRIBE,
                          WAMPMsgType.UNSUBSCRIBE):
            return await self.pubsub_action(data)
        elif msg_type in (WAMPMsgType.PUBLISH,):
            return NotImplementedError()
        else:
            raise Exception("Unknown call")
