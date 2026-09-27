import asyncio

import pytest

import serverwamp
from serverwamp.protocol import WAMPMsgType

from memory_connection import TIMEOUT, MemoryConnection, run

REALM_URI = 'test.realm'


class TrackedMemoryConnection(MemoryConnection):
    def __init__(self):
        super().__init__()
        self.msg_iterators = []

    def iterate_msgs(self):
        msgs = super().iterate_msgs()
        self.msg_iterators.append(msgs)
        return msgs


def build_app():
    realm = serverwamp.Realm(REALM_URI)
    app = serverwamp.Application(allow_default_realm=False)
    app.add_realm(realm)
    return app


@pytest.mark.parametrize('realm_uri, first_reply', (
    (REALM_URI, WAMPMsgType.WELCOME),
    ('unknown.realm', WAMPMsgType.ABORT),
))
def test_single_msg_iterator_closed_after_connection(realm_uri, first_reply):
    async def exercise():
        connection = TrackedMemoryConnection()
        handling = asyncio.ensure_future(
            build_app().handle_connection(connection)
        )
        connection.inbound.put_nowait([WAMPMsgType.HELLO, realm_uri, {}])
        reply = await connection.receive()
        assert reply[0] == first_reply

        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)
        return connection.msg_iterators

    msg_iterators = run(exercise())
    assert len(msg_iterators) == 1
    assert msg_iterators[0].ag_frame is None
