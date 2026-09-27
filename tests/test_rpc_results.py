import asyncio

import pytest

import serverwamp
from serverwamp.protocol import WAMPMsgType

from memory_connection import TIMEOUT, MemoryConnection, run

REALM_URI = 'test.realm'


def as_lists(value):
    """Normalizes tuples to lists, as they'd arrive after serialization."""
    if isinstance(value, (list, tuple)):
        return [as_lists(item) for item in value]
    return value


def build_app(procedure):
    routes = serverwamp.RPCRouteSet()
    routes.route('procedure')(procedure)
    realm = serverwamp.Realm(REALM_URI)
    realm.add_rpc_routes(routes)
    app = serverwamp.Application(allow_default_realm=False)
    app.add_realm(realm)
    return app


async def call(app, call_options=None):
    connection = MemoryConnection()
    handling = asyncio.ensure_future(app.handle_connection(connection))
    connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
    welcome = await connection.receive()
    assert welcome[0] == WAMPMsgType.WELCOME

    connection.inbound.put_nowait(
        [WAMPMsgType.CALL, 1, call_options or {}, 'procedure']
    )
    results = []
    while True:
        result = as_lists(await connection.receive())
        results.append(result)
        if not result[2].get('progress'):
            break

    await connection.close()
    await asyncio.wait_for(handling, TIMEOUT)
    return results


def returning(value):
    async def procedure():
        return value
    return procedure


@pytest.mark.parametrize('return_value, expected_payload', (
    (None, []),
    ('hello', [['hello']]),
    (b'raw', [[b'raw']]),
    (42, [[42]]),
    (4.2, [[4.2]]),
    (True, [[True]]),
    ((None,), [[None]]),
    (('Peanut Butter', 'Jelly'), [['Peanut Butter', 'Jelly']]),
    (['Bread'], [['Bread']]),
    ((), []),
    ({'year': 2020}, [[], {'year': 2020}]),
    (serverwamp.RPCResult(args=(None,)), [[None]]),
))
def test_returned_value_result_payload(return_value, expected_payload):
    results = run(call(build_app(returning(return_value))))
    assert results == [
        [WAMPMsgType.CALL_RESULT, 1, {}] + expected_payload
    ]


def test_progressive_handler_final_single_value():
    async def procedure():
        yield serverwamp.RPCProgressReport(args=('halfway',))
        yield 'done'

    results = run(call(
        build_app(procedure),
        call_options={'receive_progress': True}
    ))
    assert results == [
        [WAMPMsgType.CALL_RESULT, 1, {'progress': True}, ['halfway']],
        [WAMPMsgType.CALL_RESULT, 1, {}, ['done']],
    ]
