"""Checks that events reach a subscriber only after its SUBSCRIBED, and that
subscription handlers can turn subscriptions down.
"""
import logging

import anyio

import serverwamp
from serverwamp.protocol import WAMPMsgType

from stream_connection import TIMEOUT, StreamConnection

REALM_URI = 'test.realm'
HELLO = [WAMPMsgType.HELLO, REALM_URI, {}]
TOPIC = 'com.example.prices'


def build_app(topics):
    realm = serverwamp.Realm(REALM_URI)
    realm.add_topic_routes(topics)
    app = serverwamp.Application(allow_default_realm=False)
    app.add_realm(realm)
    return app


def run_client(app, client, connection_class=StreamConnection):
    async def exercise():
        connection = connection_class()
        with anyio.fail_after(TIMEOUT):
            async with anyio.create_task_group() as tasks:
                tasks.start_soon(app.handle_connection, connection)
                await client(connection)
                await connection.close()

    anyio.run(exercise)


async def subscribe(connection):
    await connection.deliver(HELLO)
    assert (await connection.receive())[0] == WAMPMsgType.WELCOME
    await connection.deliver([WAMPMsgType.SUBSCRIBE, 1, {}, TOPIC])


def test_handler_events_follow_subscribed():
    topics = serverwamp.TopicRouteSet()

    @topics.route(TOPIC)
    async def greet(session, topic_uri):
        await session.send_event(topic_uri, args=(101.25,))
        await session.send_event(topic_uri, args=(101.5,))
        yield

    async def client(connection):
        await subscribe(connection)
        subscribed = await connection.receive()
        assert subscribed[:2] == (WAMPMsgType.SUBSCRIBED, 1)
        for price in (101.25, 101.5):
            event = await connection.receive()
            assert (event[0], event[1], event[4]) == (WAMPMsgType.EVENT, subscribed[2], (price,))

    run_client(build_app(topics), client)


def test_other_events_held_while_subscribing():
    sessions = []
    release = anyio.Event()
    topics = serverwamp.TopicRouteSet()

    @topics.route(TOPIC)
    async def slow_to_subscribe(session):
        sessions.append(session)
        await release.wait()
        yield

    async def client(connection):
        await subscribe(connection)
        while not sessions:
            await anyio.sleep(0)
        # Such as from a publisher while the handler is still running.
        await sessions[0].send_event(TOPIC, args=('early',))
        release.set()
        assert (await connection.receive())[0] == WAMPMsgType.SUBSCRIBED
        event = await connection.receive()
        assert (event[0], event[4]) == (WAMPMsgType.EVENT, ('early',))

    run_client(build_app(topics), client)


def test_events_sent_while_held_events_drain_stay_in_order():
    sessions = []
    sending_first = anyio.Event()
    resume = anyio.Event()
    topics = serverwamp.TopicRouteSet()

    @topics.route(TOPIC)
    async def greet(session, topic_uri):
        sessions.append(session)
        await session.send_event(topic_uri, args=('first',))
        yield

    class PausingConnection(StreamConnection):
        async def send_msg(self, msg):
            if msg[0] == WAMPMsgType.EVENT and msg[4] == ('first',):
                sending_first.set()
                await resume.wait()
            await super().send_msg(msg)

    async def client(connection):
        await subscribe(connection)
        await sending_first.wait()
        await sessions[0].send_event(TOPIC, args=('second',))
        resume.set()
        assert (await connection.receive())[0] == WAMPMsgType.SUBSCRIBED
        for update in ('first', 'second'):
            assert (await connection.receive())[4] == (update,)

    run_client(build_app(topics), client, PausingConnection)


def test_held_events_dropped_when_subscribing_fails(caplog):
    topics = serverwamp.TopicRouteSet()

    @topics.route(TOPIC)
    async def fails(session, topic_uri):
        await session.send_event(topic_uri, args=('never sent',))
        raise RuntimeError('Subscription handler failed.')
        yield

    async def client(connection):
        await subscribe(connection)
        assert await connection.receive() == (
            WAMPMsgType.ERROR, WAMPMsgType.SUBSCRIBE, 1, {}, 'wamp.error.runtime_error'
        )

    with caplog.at_level(logging.ERROR, logger='serverwamp'):
        run_client(build_app(topics), client)
    assert 'Subscription handler failed.' in caplog.text


def test_subscribe_error(caplog):
    events = []
    topics = serverwamp.TopicRouteSet()

    @topics.route(TOPIC)
    async def turns_down(session, topic_uri):
        await session.send_event(topic_uri, args=('never sent',))
        try:
            raise serverwamp.SubscribeError('wamp.error.not_authorized')
            yield
            events.append('torn down')
        finally:
            events.append('finally')

    async def client(connection):
        await subscribe(connection)
        assert await connection.receive() == (
            WAMPMsgType.ERROR, WAMPMsgType.SUBSCRIBE, 1, {}, 'wamp.error.not_authorized'
        )
        # It can be subscribed to again.
        await connection.deliver([WAMPMsgType.SUBSCRIBE, 2, {}, TOPIC])
        assert (await connection.receive())[:2] == (WAMPMsgType.ERROR, WAMPMsgType.SUBSCRIBE)

    with caplog.at_level(logging.ERROR, logger='serverwamp'):
        run_client(build_app(topics), client)
    # Turning a subscription down isn't an error to log, and the code after
    # the yield is for subscriptions that were made.
    assert not caplog.records
    assert events == ['finally', 'finally']


def test_events_after_subscribed():
    sessions = []
    topics = serverwamp.TopicRouteSet()

    @topics.route(TOPIC)
    async def remembers(session):
        sessions.append(session)
        yield

    async def client(connection):
        await subscribe(connection)
        assert (await connection.receive())[0] == WAMPMsgType.SUBSCRIBED
        for update in ('first', 'second'):
            await sessions[0].send_event(TOPIC, args=(update,))
            assert (await connection.receive())[4] == (update,)

    run_client(build_app(topics), client)
