import asyncio
import json
import logging

import msgpack
import pytest

aiohttp = pytest.importorskip('aiohttp')
from aiohttp import WSMsgType, web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import serverwamp  # noqa: E402
from serverwamp.helpers import pack_uint32_be  # noqa: E402
from serverwamp.protocol import WAMPMsgType  # noqa: E402

REALM_URI = 'test.realm'


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def build_web_app(handler_results):
    rpc_routes = serverwamp.RPCRouteSet()

    @rpc_routes.route('say_hello')
    async def say_hello():
        return 'hello',

    realm = serverwamp.Realm(REALM_URI)
    realm.add_rpc_routes(rpc_routes)
    wamp_app = serverwamp.Application(allow_default_realm=False)
    wamp_app.add_realm(realm)
    wamp_handler = wamp_app.aiohttp_websocket_handler()

    async def recording_handler(request):
        response = await wamp_handler(request)
        handler_results.append(response)
        return response

    web_app = web.Application()
    web_app.router.add_get('/', recording_handler)
    return web_app


async def wait_for_handler(handler_results, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if handler_results:
            return
        await asyncio.sleep(0.01)
    raise AssertionError('aiohttp request handler never finished.')


async def start_client(handler_results):
    client = TestClient(TestServer(build_web_app(handler_results)))
    await client.start_server()
    return client


def assert_no_aiohttp_errors(caplog):
    assert not [
        record for record in caplog.records
        if record.name.startswith('aiohttp')
    ]


@pytest.mark.parametrize('first_msg', (
    [WAMPMsgType.HELLO, 'unknown.realm', {}],
    [WAMPMsgType.CALL, 1, {}, 'say_hello'],
))
def test_handler_returns_websocket_response_after_abort(caplog, first_msg):
    handler_results = []

    async def exercise():
        client = await start_client(handler_results)
        try:
            ws = await client.ws_connect('/', protocols=('wamp.2.json',))
            await ws.send_json(first_msg)
            abort = await ws.receive_json()
            assert abort[0] == WAMPMsgType.ABORT
            closing = await ws.receive()
            assert closing.type in (WSMsgType.CLOSE, WSMsgType.CLOSED)
            await ws.close()

            await wait_for_handler(handler_results)
        finally:
            await client.close()

    with caplog.at_level(logging.ERROR, logger='aiohttp'):
        run(exercise())

    assert len(handler_results) == 1
    assert isinstance(handler_results[0], web.WebSocketResponse)
    assert_no_aiohttp_errors(caplog)


@pytest.mark.parametrize('ws_protocol', (
    'wamp.2.json',
    'wamp.2.json.batched',
    'wamp.2.msgpack',
    'wamp.2.msgpack.batched',
))
def test_session_call_and_goodbye(caplog, ws_protocol):
    async def exercise():
        client = await start_client([])
        try:
            ws = await client.ws_connect('/', protocols=(ws_protocol,))
            assert ws.protocol == ws_protocol
            batched = ws_protocol.endswith('.batched')
            if ws_protocol.startswith('wamp.2.json'):
                async def send(msg):
                    text = json.dumps(msg)
                    await ws.send_str(text + '\x1e' if batched else text)

                async def receive():
                    text = await ws.receive_str()
                    return json.loads(text.rstrip('\x1e'))
            else:
                async def send(msg):
                    msg_bytes = msgpack.packb(msg)
                    if batched:
                        msg_bytes = pack_uint32_be(len(msg_bytes)) + msg_bytes
                    await ws.send_bytes(msg_bytes)

                async def receive():
                    msg_bytes = await ws.receive_bytes()
                    return msgpack.unpackb(msg_bytes[4:] if batched else msg_bytes)

            await send([WAMPMsgType.HELLO, REALM_URI, {}])
            welcome = await receive()
            assert welcome[0] == WAMPMsgType.WELCOME

            await send([WAMPMsgType.CALL, 1, {}, 'say_hello'])
            result = await receive()
            assert result[0] == WAMPMsgType.CALL_RESULT
            assert result[1] == 1
            assert result[3] == ['hello']

            await send([WAMPMsgType.GOODBYE, {}, 'wamp.close.close_realm'])
            goodbye = await receive()
            assert goodbye[0] == WAMPMsgType.GOODBYE
            await ws.close()
        finally:
            await client.close()

    with caplog.at_level(logging.ERROR, logger='aiohttp'):
        run(exercise())

    assert_no_aiohttp_errors(caplog)
