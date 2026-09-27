import asyncio

import pytest

import serverwamp
from serverwamp.protocol import WAMPMsgType

from memory_connection import TIMEOUT, MemoryConnection, run

REALM_URI = 'test.realm'


def build_app(synchronize_requests):
    routes = serverwamp.RPCRouteSet()

    @routes.route('slow')
    async def slow():
        await asyncio.sleep(0.05)
        return 'slow'

    @routes.route('fast')
    async def fast():
        return 'fast'

    realm = serverwamp.Realm(REALM_URI)
    realm.add_rpc_routes(routes)
    app = serverwamp.Application(
        allow_default_realm=False,
        synchronize_requests=synchronize_requests
    )
    app.add_realm(realm)
    return app


async def call_slow_then_fast(app):
    connection = MemoryConnection()
    handling = asyncio.ensure_future(app.handle_connection(connection))
    connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
    welcome = await connection.receive()
    assert welcome[0] == WAMPMsgType.WELCOME

    connection.inbound.put_nowait([WAMPMsgType.CALL, 1, {}, 'slow'])
    connection.inbound.put_nowait([WAMPMsgType.CALL, 2, {}, 'fast'])
    results = [await connection.receive(), await connection.receive()]

    await connection.close()
    await asyncio.wait_for(handling, TIMEOUT)
    return [(result[1], result[3]) for result in results]


@pytest.mark.parametrize('synchronize_requests, expected_order', (
    (True, [(1, ('slow',)), (2, ('fast',))]),
    (False, [(2, ('fast',)), (1, ('slow',))]),
))
def test_request_order(synchronize_requests, expected_order):
    app = build_app(synchronize_requests)
    assert run(call_slow_then_fast(app)) == expected_order
