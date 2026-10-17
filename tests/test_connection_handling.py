import asyncio
import gc
import logging

import pytest

import serverwamp
from serverwamp.application import default_protocol_rpc_handler
from serverwamp.protocol import WAMPMsgType, WAMPRPCRequest
from serverwamp.session import WAMPSession

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
        assert abort[2] == 'wamp.error.protocol_violation'
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
        assert abort[2] == 'wamp.error.protocol_violation'
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


def test_duplicate_subscribe_returns_existing_subscription():
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

        sub_ids = []
        for request_id in (1, 2):
            connection.inbound.put_nowait(
                [WAMPMsgType.SUBSCRIBE, request_id, {}, 'test.topic']
            )
            subscribed = await connection.receive()
            assert subscribed[:2] == (WAMPMsgType.SUBSCRIBED, request_id)
            sub_ids.append(subscribed[2])
        assert sub_ids[0] == sub_ids[1]

        # A single UNSUBSCRIBE ends the one subscription.
        connection.inbound.put_nowait([WAMPMsgType.UNSUBSCRIBE, 3, sub_ids[0]])
        assert await connection.receive() == (WAMPMsgType.UNSUBSCRIBED, 3)
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())
    assert topic_events == ['subscribed', 'unsubscribed']


def test_subscribe_to_unrouted_topic_errors():
    topic_routes = serverwamp.TopicRouteSet()

    @topic_routes.prefix_route('test.routed.')
    async def subscribe(topic_uri):
        yield

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
            [WAMPMsgType.SUBSCRIBE, 1, {}, 'test.unrouted']
        )
        assert await connection.receive() == (
            WAMPMsgType.ERROR, WAMPMsgType.SUBSCRIBE, 1, {},
            'wamp.error.invalid_uri'
        )

        # The session is still open, and a routed topic can be subscribed to.
        connection.inbound.put_nowait(
            [WAMPMsgType.SUBSCRIBE, 2, {}, 'test.routed.topic']
        )
        subscribed = await connection.receive()
        assert subscribed[:2] == (WAMPMsgType.SUBSCRIBED, 2)
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())


@pytest.mark.parametrize('hello_details', (
    {},
    {'authmethods': None},
    {'authmethods': ['ticket']},
))
def test_failed_transport_authentication_aborts(hello_details):
    async def reject(session):
        return None

    async def exercise():
        connection = MemoryConnection()
        realm = serverwamp.Realm(REALM_URI)
        realm.add_transport_authenticator(reject)
        app = serverwamp.Application(allow_default_realm=False)
        app.add_realm(realm)
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait(
            [WAMPMsgType.HELLO, REALM_URI, hello_details]
        )
        abort = await connection.receive()
        assert abort[0] == WAMPMsgType.ABORT
        assert abort[2] == 'wamp.error.authentication_failed'
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())


class DisconnectingMemoryConnection(MemoryConnection):
    """Fails sends once closed, as transports do after a disconnect."""
    def __init__(self):
        super().__init__()
        self.closed = False

    async def send_msg(self, msg):
        if self.closed:
            raise serverwamp.ConnectionClosed()
        await super().send_msg(msg)

    async def close(self):
        self.closed = True
        await super().close()


def live_sessions():
    return sum(isinstance(obj, WAMPSession) for obj in gc.get_objects())


@pytest.mark.parametrize('synchronize_requests', (False, True))
def test_disconnect_with_rpcs_in_flight(caplog, synchronize_requests):
    finished_calls = []
    rpc_routes = serverwamp.RPCRouteSet()

    @rpc_routes.route('slow')
    async def slow(call_id):
        await asyncio.sleep(0.05)
        finished_calls.append(call_id)
        return 'done'

    async def exercise():
        connection = DisconnectingMemoryConnection()
        realm = serverwamp.Realm(REALM_URI)
        realm.add_rpc_routes(rpc_routes)
        app = serverwamp.Application(
            allow_default_realm=False,
            synchronize_requests=synchronize_requests
        )
        app.add_realm(realm)
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await connection.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        for request_id in (1, 2):
            connection.inbound.put_nowait(
                [WAMPMsgType.CALL, request_id, {}, 'slow', [request_id]]
            )
        await asyncio.sleep(0)
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    gc.collect()
    gc.disable()
    try:
        with caplog.at_level(logging.WARNING):
            run(exercise())
        # Freed by reference counting alone, not left for the cyclic GC.
        assert live_sessions() == 0
    finally:
        gc.enable()

    assert not caplog.records
    # With synchronize_requests, the session stops handling messages once the
    # client is gone. Otherwise, calls already started all finish.
    assert finished_calls == ([1] if synchronize_requests else [1, 2])


@pytest.mark.parametrize('disconnect', (False, True))
def test_progressive_rpc_closed_when_handled(disconnect):
    events = []
    rpc_routes = serverwamp.RPCRouteSet()

    @rpc_routes.route('progressive')
    async def progressive():
        try:
            yield serverwamp.RPCProgressReport(args=('halfway',))
            await asyncio.sleep(0.05)
            yield 'done'
            # Not reached; the result above is final.
            yield 'extra'
        finally:
            events.append('procedure closed')

    async def rpc_handler(request, session):
        try:
            await default_protocol_rpc_handler(request, session)
        finally:
            events.append('call handled')

    async def exercise():
        connection = DisconnectingMemoryConnection()
        realm = serverwamp.Realm(REALM_URI)
        realm.add_rpc_routes(rpc_routes)
        app = serverwamp.Application(
            allow_default_realm=False,
            protocol_request_handlers={WAMPRPCRequest: rpc_handler}
        )
        app.add_realm(realm)
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await connection.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        connection.inbound.put_nowait([
            WAMPMsgType.CALL, 1, {'receive_progress': True}, 'progressive'
        ])
        progress = await connection.receive()
        assert progress[2] == {'progress': True}
        if not disconnect:
            result = await connection.receive()
            assert result[3] == ('done',)
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())
    # The procedure is closed as soon as its call is handled, not later by
    # the event loop's async generator finalizer.
    assert events[:2] == ['procedure closed', 'call handled']


def test_close_sessions_after_client_left():
    async def exercise():
        connection = DisconnectingMemoryConnection()
        app = build_app()
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await connection.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        # The transport is gone, but the session hasn't noticed yet.
        connection.closed = True
        await app.close_sessions()

        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())


def test_close_sessions_says_system_shutdown():
    async def exercise():
        connection = MemoryConnection()
        app = build_app()
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait([WAMPMsgType.HELLO, REALM_URI, {}])
        welcome = await connection.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        await app.close_sessions()
        assert await connection.receive() == (
            WAMPMsgType.GOODBYE, {}, 'wamp.close.system_shutdown'
        )

        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())


@pytest.mark.parametrize('end_session', ('close', 'abort'))
def test_end_session_after_client_left(end_session):
    async def exercise():
        connection = DisconnectingMemoryConnection()
        session = WAMPSession(connection, serverwamp.Realm(REALM_URI),
                              tasks=None)
        await session.mark_authenticated()
        await connection.close()

        await getattr(session, end_session)('wamp.close.system_shutdown')
        assert not session.is_open

    run(exercise())
