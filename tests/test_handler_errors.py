"""Checks that errors from subscription and session lifespan handlers are
answered per WAMP spec instead of ending the connection.
"""
import logging

import anyio
import pytest

import serverwamp
from serverwamp.adapters.anyio import AnyioAsyncSupport
from serverwamp.adapters.asyncio import AsyncioAsyncSupport
from serverwamp.adapters.trio import TrioAsyncSupport
from serverwamp.protocol import WAMPMsgType

from stream_connection import TIMEOUT, StreamConnection

# Lifespan handlers start in each async support's task group, so how they fail
# is checked on each. Other handler errors are handled the same on any.
ALL_ASYNC_SUPPORTS = (
    (AsyncioAsyncSupport, 'asyncio'),
    (AnyioAsyncSupport, 'asyncio'),
    (AnyioAsyncSupport, 'trio'),
    (TrioAsyncSupport, 'trio'),
)

REALM_URI = 'test.realm'
HELLO = [WAMPMsgType.HELLO, REALM_URI, {}]
GOODBYE = [WAMPMsgType.GOODBYE, {}, 'wamp.close.goodbye_and_out']


def build_app(async_support=AsyncioAsyncSupport, topics=None, lifespan_handlers=(),
              authenticated_only=True):
    realm = serverwamp.Realm(REALM_URI)
    if topics:
        realm.add_topic_routes(topics)
    for handler in lifespan_handlers:
        realm.add_session_lifespan_handler(handler, authenticated_only=authenticated_only)
    app = serverwamp.Application(allow_default_realm=False, async_support=async_support)
    app.add_realm(realm)
    return app


def run_client(app, client, async_support=AsyncioAsyncSupport, backend='asyncio'):
    async def exercise():
        connection = StreamConnection()
        with anyio.fail_after(TIMEOUT):
            async with async_support.launch_task_group() as tasks:
                await tasks.spawn(app.handle_connection, connection)
                await client(connection)
                await connection.close()

    anyio.run(exercise, backend=backend)


def lifespan_handler(name, events):
    async def handler():
        events.append(f'{name} started')
        yield
        events.append(f'{name} ended')
    return handler


def failing_topics(events):
    topics = serverwamp.TopicRouteSet()

    @topics.route('raises')
    async def raises():
        raise RuntimeError('Subscription handler failed.')
        yield

    @topics.route('unfillable')
    async def unfillable(price_feed):
        yield

    @topics.route('fails_teardown')
    async def fails_teardown():
        events.append('subscribed')
        yield
        raise RuntimeError('Subscription teardown failed.')

    @topics.route('works')
    async def works():
        yield

    return topics


@pytest.mark.parametrize('topic, logged', (
    ('raises', 'Subscription handler failed.'),
    ('unfillable', "No value for parameter 'price_feed'"),
))
def test_subscription_handler_error(caplog, topic, logged):
    app = build_app(topics=failing_topics([]))

    async def client(connection):
        await connection.deliver(HELLO)
        assert (await connection.receive())[0] == WAMPMsgType.WELCOME
        await connection.deliver([WAMPMsgType.SUBSCRIBE, 1, {}, topic])
        assert await connection.receive() == (
            WAMPMsgType.ERROR, WAMPMsgType.SUBSCRIBE, 1, {}, 'wamp.error.runtime_error'
        )
        # The session carries on, and can subscribe to the topic later.
        await connection.deliver([WAMPMsgType.SUBSCRIBE, 2, {}, 'works'])
        assert (await connection.receive())[:2] == (WAMPMsgType.SUBSCRIBED, 2)

    with caplog.at_level(logging.ERROR, logger='serverwamp'):
        run_client(app, client)
    assert logged in caplog.text
    assert not app._subscription_exits


def test_subscription_teardown_error_on_unsubscribe(caplog):
    app = build_app(topics=failing_topics([]))

    async def client(connection):
        await connection.deliver(HELLO)
        assert (await connection.receive())[0] == WAMPMsgType.WELCOME
        await connection.deliver([WAMPMsgType.SUBSCRIBE, 1, {}, 'fails_teardown'])
        subscribed = await connection.receive()
        assert subscribed[0] == WAMPMsgType.SUBSCRIBED
        await connection.deliver([WAMPMsgType.UNSUBSCRIBE, 2, subscribed[2]])
        assert await connection.receive() == (WAMPMsgType.UNSUBSCRIBED, 2)

    with caplog.at_level(logging.ERROR, logger='serverwamp'):
        run_client(app, client)
    assert 'Subscription teardown failed.' in caplog.text


def test_teardown_errors_dont_stop_other_teardown(caplog):
    events = []

    async def fails_teardown():
        yield
        raise RuntimeError('Lifespan teardown failed.')

    app = build_app(
        topics=failing_topics(events),
        lifespan_handlers=(fails_teardown, lifespan_handler('other', events))
    )

    async def client(connection):
        await connection.deliver(HELLO)
        assert (await connection.receive())[0] == WAMPMsgType.WELCOME
        await connection.deliver([WAMPMsgType.SUBSCRIBE, 1, {}, 'fails_teardown'])
        assert (await connection.receive())[0] == WAMPMsgType.SUBSCRIBED

    with caplog.at_level(logging.ERROR, logger='serverwamp'):
        run_client(app, client)
    assert events == ['other started', 'subscribed', 'other ended']
    assert 'Subscription teardown failed.' in caplog.text
    assert 'Lifespan teardown failed.' in caplog.text
    assert not app._session_lifespan_exits


async def raises():
    raise RuntimeError('Lifespan handler failed.')
    yield


async def client_aborted(connection):
    await connection.deliver(HELLO)
    assert await connection.receive() == (
        WAMPMsgType.ABORT, {}, 'wamp.error.runtime_error'
    )


async def client_said_goodbye(connection):
    await connection.deliver(HELLO)
    assert (await connection.receive())[0] == WAMPMsgType.WELCOME
    assert await connection.receive() == (
        WAMPMsgType.GOODBYE, {}, 'wamp.error.runtime_error'
    )
    # Anything but the client's GOODBYE in reply is ignored.
    await connection.deliver([WAMPMsgType.SUBSCRIBE, 1, {}, 'anything'])
    await connection.deliver(GOODBYE)


@pytest.mark.parametrize('async_support, backend', ALL_ASYNC_SUPPORTS)
@pytest.mark.parametrize('authenticated_only, client', (
    (False, client_aborted),
    (True, client_said_goodbye),
))
def test_lifespan_handler_error_ends_session(
    async_support, backend, caplog, authenticated_only, client
):
    events = []
    app = build_app(
        async_support,
        lifespan_handlers=(raises, lifespan_handler('other', events)),
        authenticated_only=authenticated_only
    )

    with caplog.at_level(logging.ERROR, logger='serverwamp'):
        run_client(app, client, async_support, backend)
    assert 'Lifespan handler failed.' in caplog.text
    # The handler that started is still torn down.
    assert events == ['other started', 'other ended']
    assert not app._session_lifespan_exits
    assert not app._active_sessions


async def unfillable(metrics):
    yield


async def never_yields():
    return
    yield


@pytest.mark.parametrize('failing_handler, logged', (
    (unfillable, "No value for parameter 'metrics'"),
    (never_yields, 'ended without yielding'),
))
def test_lifespan_handler_failures(caplog, failing_handler, logged):
    app = build_app(lifespan_handlers=(failing_handler,))

    with caplog.at_level(logging.ERROR, logger='serverwamp'):
        run_client(app, client_said_goodbye)
    assert logged in caplog.text
