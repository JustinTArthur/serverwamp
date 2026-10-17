import asyncio
import json
import logging

import msgpack
import pytest

aiohttp = pytest.importorskip('aiohttp')
from aiohttp import WSMsgType, web  # noqa: E402

import serverwamp  # noqa: E402
from serverwamp.helpers import pack_uint32_be  # noqa: E402
from serverwamp.protocol import WAMPMsgType  # noqa: E402

REALM_URI = 'test.realm'

AIOHTTP_VERSION = tuple(
    int(part) for part in aiohttp.__version__.split('.')[:2]
)
# Whether aiohttp cancels a request handler when its client disconnects:
# always before 3.8, never in 3.8, and optionally, off by default, from 3.9.
HANDLER_CANCELLATION_OPTIONAL = AIOHTTP_VERSION >= (3, 9)


@pytest.fixture(params=(False, True), ids=('uncancelled', 'cancelled'))
def handler_cancellation(request):
    if not HANDLER_CANCELLATION_OPTIONAL:
        always_cancels = AIOHTTP_VERSION < (3, 8)
        if request.param != always_cancels:
            pytest.skip(f'aiohttp {aiohttp.__version__} '
                        f'{"always" if always_cancels else "never"} cancels '
                        f'handlers.')
    return request.param


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def build_web_app(handler_results, slow_calls):
    rpc_routes = serverwamp.RPCRouteSet()

    @rpc_routes.route('say_hello')
    async def say_hello():
        return 'hello',

    @rpc_routes.route('slow')
    async def slow():
        try:
            await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            slow_calls.append('cancelled')
            raise
        slow_calls.append('finished')
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
    return web_app, wamp_app


async def wait_until(condition, failure, timeout=5.0):
    for _ in range(int(timeout / 0.01)):
        if condition():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(failure)


async def wait_for_handler(handler_results):
    await wait_until(lambda: handler_results,
                     'aiohttp request handler never finished.')


class Client:
    """Connects to the test app served on a local port."""
    def __init__(self, runner, http, base_url, wamp_app):
        self._runner = runner
        self._http = http
        self._base_url = base_url
        self.wamp_app = wamp_app

    def ws_connect(self, path, **kwargs):
        return self._http.ws_connect(self._base_url + path, **kwargs)

    async def close(self):
        await self._http.close()
        await self._runner.cleanup()


async def start_client(handler_results, handler_cancellation, slow_calls=None):
    # Served as aiohttp servers are, rather than with aiohttp's TestServer,
    # which always cancels the handlers of clients that disconnect.
    web_app, wamp_app = build_web_app(
        handler_results,
        [] if slow_calls is None else slow_calls
    )
    if HANDLER_CANCELLATION_OPTIONAL:
        runner = web.AppRunner(web_app,
                               handler_cancellation=handler_cancellation)
    else:
        runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    host, port = runner.addresses[0][:2]
    return Client(runner, aiohttp.ClientSession(), f'http://{host}:{port}',
                  wamp_app)


def assert_no_aiohttp_errors(caplog):
    assert not [
        record for record in caplog.records
        if record.name.startswith('aiohttp')
    ]


@pytest.mark.parametrize('first_msg', (
    [WAMPMsgType.HELLO, 'unknown.realm', {}],
    [WAMPMsgType.CALL, 1, {}, 'say_hello'],
))
def test_handler_returns_websocket_response_after_abort(caplog, first_msg,
                                                        handler_cancellation):
    handler_results = []

    async def exercise():
        client = await start_client(handler_results, handler_cancellation)
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
def test_malformed_message_aborts(caplog, ws_protocol, payload, in_session,
                                  handler_cancellation):
    handler_results = []
    # The client disconnecting cancels the handler during session cleanup, so
    # it doesn't return.
    handler_cancelled = in_session and handler_cancellation
    uses_json = ws_protocol.startswith('wamp.2.json')
    batched = ws_protocol.endswith('.batched')

    async def receive(ws):
        if uses_json:
            return json.loads((await ws.receive_str()).rstrip('\x1e'))
        msg_bytes = await ws.receive_bytes()
        return msgpack.unpackb(msg_bytes[4:] if batched else msg_bytes)

    async def exercise():
        client = await start_client(handler_results, handler_cancellation)
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

            if handler_cancelled:
                # Give it time to log any error that escaped instead.
                await asyncio.sleep(0.1)
            else:
                await wait_for_handler(handler_results)
        finally:
            await client.close()

    with caplog.at_level(logging.ERROR, logger='aiohttp'):
        run(exercise())

    if not handler_cancelled:
        assert len(handler_results) == 1
        assert isinstance(handler_results[0], web.WebSocketResponse)
    assert_no_aiohttp_errors(caplog)


@pytest.mark.parametrize('ws_protocol', (
    'wamp.2.json',
    'wamp.2.json.batched',
    'wamp.2.msgpack',
    'wamp.2.msgpack.batched',
))
def test_session_call_and_goodbye(caplog, ws_protocol, handler_cancellation):
    async def exercise():
        client = await start_client([], handler_cancellation)
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


def test_disconnect_with_rpcs_in_flight(caplog, handler_cancellation):
    handler_results = []
    slow_calls = []

    async def exercise():
        client = await start_client(handler_results, handler_cancellation,
                                    slow_calls)
        try:
            ws = await client.ws_connect('/', protocols=('wamp.2.json',))
            await ws.send_json([WAMPMsgType.HELLO, REALM_URI, {}])
            welcome = await ws.receive_json()
            assert welcome[0] == WAMPMsgType.WELCOME

            await ws.send_json([WAMPMsgType.CALL, 1, {}, 'slow'])
            await ws.send_json([WAMPMsgType.CALL, 2, {}, 'slow'])
            await asyncio.sleep(0.01)
            await ws.close()

            if handler_cancellation:
                # Cancelling the handler cancels the session's calls.
                await wait_until(lambda: len(slow_calls) == 2,
                                 'Calls weren\'t cancelled.')
            else:
                await wait_for_handler(handler_results)
            await wait_until(lambda: not client.wamp_app._active_sessions,
                             'Session wasn\'t cleaned up.')
        finally:
            await client.close()

    with caplog.at_level(logging.DEBUG):
        run(exercise())

    assert not [
        record for record in caplog.records
        if record.levelno >= logging.ERROR
    ]
    disconnected_replies = [
        record for record in caplog.records
        if record.name == 'serverwamp.session' and 'disconnected' in
        record.getMessage()
    ]
    if handler_cancellation:
        assert not handler_results
        assert slow_calls == ['cancelled', 'cancelled']
        assert not disconnected_replies
    else:
        assert len(handler_results) == 1
        # Both calls ran to completion and found the client gone.
        assert slow_calls == ['finished', 'finished']
        assert len(disconnected_replies) == 2
