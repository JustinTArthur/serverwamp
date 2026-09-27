import asyncio
import json

import msgpack
import pytest

import serverwamp
from serverwamp.helpers import pack_uint32_be
from serverwamp.protocol import WAMPMsgType

from memory_connection import TIMEOUT, run

REALM_URI = 'test.realm'
BATCH_SPLITTER = '\x1e'


def build_asgi_app():
    rpc_routes = serverwamp.RPCRouteSet()

    @rpc_routes.route('echo')
    async def echo(value):
        return value

    realm = serverwamp.Realm(REALM_URI)
    realm.add_rpc_routes(rpc_routes)
    wamp_app = serverwamp.Application(allow_default_realm=False)
    wamp_app.add_realm(realm)
    return wamp_app.asgi_application()


class ASGIClient:
    """Drives an ASGI WebSocket application in-memory, (de)serializing WAMP
    messages for the negotiated subprotocol."""
    def __init__(self, ws_protocol):
        self.ws_protocol = ws_protocol
        self.batched = ws_protocol.endswith('.batched')
        self.uses_json = ws_protocol.startswith('wamp.2.json')
        self._to_app = asyncio.Queue()
        self._from_app = asyncio.Queue()
        self._received = []

    async def start(self, asgi_app):
        scope = {
            'type': 'websocket',
            'subprotocols': [self.ws_protocol],
            'headers': [],
            'path': '/',
        }
        self.handling = asyncio.ensure_future(
            asgi_app(scope, self._to_app.get, self._from_app.put)
        )
        accept = await self._next_event()
        assert accept == {
            'type': 'websocket.accept',
            'subprotocol': self.ws_protocol
        }

    async def _next_event(self):
        return await asyncio.wait_for(self._from_app.get(), TIMEOUT)

    def send(self, *msgs):
        """Sends messages in a single WebSocket message."""
        if self.uses_json:
            if self.batched:
                text = ''.join(json.dumps(msg) + BATCH_SPLITTER for msg in msgs)
            else:
                text, = (json.dumps(msg) for msg in msgs)
            event = {'type': 'websocket.receive', 'text': text}
        else:
            if self.batched:
                data = b''.join(
                    pack_uint32_be(len(msg_bytes)) + msg_bytes
                    for msg_bytes in (msgpack.packb(msg) for msg in msgs)
                )
            else:
                data, = (msgpack.packb(msg) for msg in msgs)
            event = {'type': 'websocket.receive', 'bytes': data}
        self._to_app.put_nowait(event)

    async def receive(self):
        while not self._received:
            event = await self._next_event()
            assert event['type'] == 'websocket.send', event
            if self.uses_json:
                text = event['text']
                if self.batched:
                    assert text.endswith(BATCH_SPLITTER)
                    self._received.extend(
                        json.loads(json_text)
                        for json_text in text.split(BATCH_SPLITTER)
                        if json_text
                    )
                else:
                    self._received.append(json.loads(text))
            else:
                data = event['bytes']
                if self.batched:
                    while data:
                        msg_len = int.from_bytes(data[:4], 'big')
                        self._received.append(
                            msgpack.unpackb(data[4:4 + msg_len])
                        )
                        data = data[4 + msg_len:]
                else:
                    self._received.append(msgpack.unpackb(data))
        return self._received.pop(0)

    async def disconnect(self):
        self._to_app.put_nowait({'type': 'websocket.disconnect'})
        await asyncio.wait_for(self.handling, TIMEOUT)


WS_PROTOCOLS = (
    'wamp.2.json',
    'wamp.2.json.batched',
    'wamp.2.msgpack',
    'wamp.2.msgpack.batched',
)


@pytest.mark.parametrize('ws_protocol', WS_PROTOCOLS)
def test_session_call_and_goodbye(ws_protocol):
    async def exercise():
        client = ASGIClient(ws_protocol)
        await client.start(build_asgi_app())

        client.send([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await client.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        client.send([WAMPMsgType.CALL, 1, {}, 'echo', ['hello']])
        assert await client.receive() == [
            WAMPMsgType.CALL_RESULT, 1, {}, ['hello']
        ]

        client.send([WAMPMsgType.GOODBYE, {}, 'wamp.close.close_realm'])
        goodbye = await client.receive()
        assert goodbye[0] == WAMPMsgType.GOODBYE

        await client.disconnect()

    run(exercise())


@pytest.mark.parametrize('ws_protocol', (
    'wamp.2.json.batched',
    'wamp.2.msgpack.batched',
))
def test_batched_messages_in_one_websocket_message(ws_protocol):
    async def exercise():
        client = ASGIClient(ws_protocol)
        await client.start(build_asgi_app())

        client.send([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await client.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        client.send(
            [WAMPMsgType.CALL, 1, {}, 'echo', ['first']],
            [WAMPMsgType.CALL, 2, {}, 'echo', ['second']],
        )
        results = [await client.receive(), await client.receive()]
        assert sorted(results) == [
            [WAMPMsgType.CALL_RESULT, 1, {}, ['first']],
            [WAMPMsgType.CALL_RESULT, 2, {}, ['second']],
        ]

        await client.disconnect()

    run(exercise())
