import asyncio

import serverwamp
from serverwamp.connection import Connection
from serverwamp.protocol import WAMPMsgType

TIMEOUT = 5.0


class MemoryConnection(Connection):
    def __init__(self):
        super().__init__()
        self.inbound = asyncio.Queue()
        self.outbound = asyncio.Queue()

    async def iterate_msgs(self):
        while True:
            msg = await self.inbound.get()
            if msg is None:
                return
            yield msg

    async def send_msg(self, msg):
        await self.outbound.put(msg)

    async def close(self):
        self.inbound.put_nowait(None)

    async def receive(self):
        return await asyncio.wait_for(self.outbound.get(), TIMEOUT)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def routes_answering(answer):
    routes = serverwamp.RPCRouteSet()

    @routes.route('which_realm')
    async def which_realm():
        return answer,

    return routes


def build_app(**app_kwargs):
    app = serverwamp.Application(**app_kwargs)
    explicit_realm = serverwamp.Realm('explicit.realm')
    explicit_realm.add_rpc_routes(routes_answering('explicit'))
    app.add_realm(explicit_realm)
    if app_kwargs.get('allow_default_realm', True):
        app.add_rpc_routes(routes_answering('default'))
    return app


async def say_hello(app, realm_uri):
    connection = MemoryConnection()
    handling = asyncio.ensure_future(app.handle_connection(connection))
    connection.inbound.put_nowait([WAMPMsgType.HELLO, realm_uri, {}])
    reply = await connection.receive()
    return connection, handling, reply


async def call_which_realm(app, realm_uri):
    connection, handling, welcome = await say_hello(app, realm_uri)
    assert welcome[0] == WAMPMsgType.WELCOME

    connection.inbound.put_nowait([WAMPMsgType.CALL, 1, {}, 'which_realm'])
    result = await connection.receive()
    assert result[0] == WAMPMsgType.CALL_RESULT

    await connection.close()
    await asyncio.wait_for(handling, TIMEOUT)
    return result[3]


def test_unconfigured_realm_uses_default_realm():
    app = build_app()
    assert run(call_which_realm(app, 'unconfigured.realm')) == ('default',)


def test_configured_realm_takes_precedence_over_default_realm():
    app = build_app()
    assert run(call_which_realm(app, 'explicit.realm')) == ('explicit',)


def test_unconfigured_realm_aborted_without_default_realm():
    app = build_app(allow_default_realm=False)

    async def exercise():
        connection, handling, abort = await say_hello(app, 'unconfigured.realm')
        await asyncio.wait_for(handling, TIMEOUT)
        return abort

    abort = run(exercise())
    assert abort[0] == WAMPMsgType.ABORT
    assert abort[2] == 'wamp.error.no_such_realm'


def test_configured_realm_works_without_default_realm():
    app = build_app(allow_default_realm=False)
    assert run(call_which_realm(app, 'explicit.realm')) == ('explicit',)
