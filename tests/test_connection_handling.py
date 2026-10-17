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


def build_app(**app_kwargs):
    realm = serverwamp.Realm(REALM_URI)
    app = serverwamp.Application(allow_default_realm=False, **app_kwargs)
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


@pytest.mark.parametrize('synchronize_requests', (False, True))
@pytest.mark.parametrize('in_session', (False, True))
@pytest.mark.parametrize('msg', (
    [],
    5,
    [WAMPMsgType.HELLO],
    [WAMPMsgType.CALL, 1, [], 'proc'],
))
def test_malformed_wamp_aborts(msg, in_session, synchronize_requests):
    async def exercise():
        connection = MemoryConnection()
        app = build_app(synchronize_requests=synchronize_requests)
        handling = asyncio.ensure_future(app.handle_connection(connection))
        if in_session:
            connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
            welcome = await connection.receive()
            assert welcome[0] == WAMPMsgType.WELCOME

        connection.inbound.put_nowait(msg)
        abort = await connection.receive()
        assert abort[0] == WAMPMsgType.ABORT
        assert abort[2] == 'wamp.error.protocol_error'
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())


@pytest.mark.parametrize('synchronize_requests', (False, True))
def test_hello_in_session_aborts(synchronize_requests):
    async def exercise():
        connection = MemoryConnection()
        app = build_app(synchronize_requests=synchronize_requests)
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await connection.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
        abort = await connection.receive()
        assert abort[0] == WAMPMsgType.ABORT
        assert abort[1] == {'message': 'Unexpected request.'}
        assert abort[2] == 'wamp.error.protocol_error'
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())


def test_unsubscribe_unknown_subscription():
    topic_events = []
    topic_routes = serverwamp.TopicRouteSet()

    @topic_routes.route('test.topic')
    async def subscribe(topic_uri):
        topic_events.append('subscribed')
        yield
        topic_events.append('unsubscribed')

    async def exercise():
        connection = MemoryConnection()
        realm = serverwamp.Realm(REALM_URI)
        realm.add_topic_routes(topic_routes)
        app = serverwamp.Application(allow_default_realm=False)
        app.add_realm(realm)
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await connection.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        connection.inbound.put_nowait(
            [WAMPMsgType.SUBSCRIBE, 1, {}, 'test.topic']
        )
        subscribed = await connection.receive()
        assert subscribed[:2] == (WAMPMsgType.SUBSCRIBED, 1)
        sub_id = subscribed[2]

        connection.inbound.put_nowait([WAMPMsgType.UNSUBSCRIBE, 2, sub_id])
        assert await connection.receive() == (WAMPMsgType.UNSUBSCRIBED, 2)

        for request_id, unknown_sub_id in ((3, sub_id), (4, 12345)):
            connection.inbound.put_nowait(
                [WAMPMsgType.UNSUBSCRIBE, request_id, unknown_sub_id]
            )
            assert await connection.receive() == (
                WAMPMsgType.ERROR, WAMPMsgType.UNSUBSCRIBE, request_id, {},
                'wamp.error.no_such_subscription'
            )

        # The session is still open.
        connection.inbound.put_nowait(
            [WAMPMsgType.GOODBYE, {}, 'wamp.close.close_realm']
        )
        goodbye = await connection.receive()
        assert goodbye[0] == WAMPMsgType.GOODBYE
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())
    assert topic_events == ['subscribed', 'unsubscribed']
