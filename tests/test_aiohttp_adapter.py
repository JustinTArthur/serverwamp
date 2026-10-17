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

    @rpc_routes.route('slow')
    async def slow():
        await asyncio.sleep(0.1)
        return 'done'

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


@pytest.mark.parametrize('in_session', (False, True))
@pytest.mark.parametrize('ws_protocol, payload', (
    ('wamp.2.json', '[48, 2, {}, "x\\q"]'),
    ('wamp.2.json.batched', '[48, 2, {}, "x\\q"]\x1e'),
    ('wamp.2.msgpack', b'\xc1'),
    ('wamp.2.msgpack.batched', b'\x00\x00'),
    ('wamp.2.msgpack.batched', pack_uint32_be(1) + b'\xc1'),
))
def test_malformed_message_aborts(caplog, ws_protocol, payload, in_session):
    handler_results = []
    uses_json = ws_protocol.startswith('wamp.2.json')
    batched = ws_protocol.endswith('.batched')

    async def receive(ws):
        if uses_json:
            return json.loads((await ws.receive_str()).rstrip('\x1e'))
        msg_bytes = await ws.receive_bytes()
        return msgpack.unpackb(msg_bytes[4:] if batched else msg_bytes)

    async def exercise():
        client = await start_client(handler_results)
        try:
            ws = await client.ws_connect('/', protocols=(ws_protocol,))
            if in_session:
                hello = [WAMPMsgType.HELLO, REALM_URI, {}]
                if uses_json:
                    text = json.dumps(hello)
                    await ws.send_str(text + '\x1e' if batched else text)
                else:
                    msg_bytes = msgpack.packb(hello)
                    if batched:
                        msg_bytes = pack_uint32_be(len(msg_bytes)) + msg_bytes
                    await ws.send_bytes(msg_bytes)
                welcome = await receive(ws)
                assert welcome[0] == WAMPMsgType.WELCOME

            if uses_json:
                await ws.send_str(payload)
            else:
                await ws.send_bytes(payload)
            abort = await receive(ws)
            assert abort[0] == WAMPMsgType.ABORT
            assert abort[2] == 'wamp.error.protocol_violation'
            closing = await ws.receive()
            assert closing.type in (WSMsgType.CLOSE, WSMsgType.CLOSED)
            await ws.close()

            if in_session:
                # aiohttp cancels the handler once the client disconnects,
                # which here lands during session cleanup, so it doesn't
                # return. Give it time to log any error that escaped instead.
                await asyncio.sleep(0.1)
            else:
                await wait_for_handler(handler_results)
        finally:
            await client.close()

    with caplog.at_level(logging.ERROR, logger='aiohttp'):
        run(exercise())

    if not in_session:
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


class ClosingWebSocket:
    """Stands in for a WebSocketResponse whose transport is closing."""
    async def _closing_send(self, data, compress=None):
        raise ConnectionResetError('Cannot write to closing transport')

    send_json = send_str = send_bytes = _closing_send

    async def close(self):
        pass


@pytest.mark.parametrize('ws_protocol', (
    'wamp.2.json',
    'wamp.2.json.batched',
    'wamp.2.msgpack',
    'wamp.2.msgpack.batched',
))
def test_send_to_closing_websocket_raises_connection_closed(ws_protocol):
    from types import SimpleNamespace

    from serverwamp.adapters.aiohttp import ws_protocol_connection_classes

    request = SimpleNamespace(cookies={}, raw_headers=(), path='/',
                              raw_path='/', query_string='', remote=None,
                              transport=None)
    connection = ws_protocol_connection_classes[ws_protocol](
        ClosingWebSocket(),
        request
    )

    async def exercise():
        with pytest.raises(serverwamp.ConnectionClosed):
            await connection.send_msg([WAMPMsgType.GOODBYE, {}, 'x'])
        with pytest.raises(serverwamp.ConnectionClosed):
            await connection.send_msgs([[WAMPMsgType.GOODBYE, {}, 'x']])
        # Nobody's left to tell, so aborting doesn't fail.
        await connection.abort('wamp.error.protocol_violation')

    run(exercise())


def test_disconnect_with_rpcs_in_flight(caplog):
    handler_results = []

    async def exercise():
        # aiohttp's TestServer cancels handlers when the client disconnects,
        # but servers don't by default, so RPCs outlive the client.
        runner = web.AppRunner(build_web_app(handler_results))
        await runner.setup()
        site = web.TCPSite(runner, '127.0.0.1', 0)
        await site.start()
        host, port = runner.addresses[0][:2]
        try:
            async with aiohttp.ClientSession() as http:
                ws = await http.ws_connect(f'http://{host}:{port}/',
                                           protocols=('wamp.2.json',))
                await ws.send_json([WAMPMsgType.HELLO, REALM_URI, {}])
                welcome = await ws.receive_json()
                assert welcome[0] == WAMPMsgType.WELCOME

                await ws.send_json([WAMPMsgType.CALL, 1, {}, 'slow'])
                await ws.send_json([WAMPMsgType.CALL, 2, {}, 'slow'])
                await asyncio.sleep(0.01)
                await ws.close()

            await wait_for_handler(handler_results)
        finally:
            await runner.cleanup()

    with caplog.at_level(logging.DEBUG):
        run(exercise())

    assert len(handler_results) == 1
    assert not [
        record for record in caplog.records
        if record.levelno >= logging.ERROR
    ]
    # Both calls ran to completion and found the client gone.
    assert len([
        record for record in caplog.records
        if record.name == 'serverwamp.session' and 'disconnected' in
        record.getMessage()
    ]) == 2
