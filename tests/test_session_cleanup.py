"""Checks that a session is cleaned up however it ends."""
import anyio
import pytest

import serverwamp
from serverwamp.adapters.anyio import AnyioAsyncSupport
from serverwamp.adapters.asyncio import AsyncioAsyncSupport
from serverwamp.adapters.trio import TrioAsyncSupport
from serverwamp.protocol import WAMPMsgType

from stream_connection import TIMEOUT, StreamConnection

pytestmark = pytest.mark.parametrize('async_support, backend', (
    (AsyncioAsyncSupport, 'asyncio'),
    (AnyioAsyncSupport, 'asyncio'),
    (AnyioAsyncSupport, 'trio'),
    (TrioAsyncSupport, 'trio'),
))

REALM_URI = 'test.realm'
TORN_DOWN = ['lifespan started', 'subscribed', 'unsubscribed', 'lifespan ended']


def build_app(async_support, events):
    async def session_lifespan(session):
        events.append('lifespan started')
        yield
        events.append('lifespan ended')

    topics = serverwamp.TopicRouteSet()

    @topics.route('test.topic')
    async def subscription(topic_uri):
        events.append('subscribed')
        yield
        events.append('unsubscribed')

    realm = serverwamp.Realm(REALM_URI)
    realm.add_session_lifespan_handler(session_lifespan, authenticated_only=False)
    realm.add_topic_routes(topics)
    app = serverwamp.Application(allow_default_realm=False,
                                 async_support=async_support)
    app.add_realm(realm)
    return app


async def subscribe(connection):
    await connection.deliver([WAMPMsgType.HELLO, REALM_URI, {}])
    assert (await connection.receive())[0] == WAMPMsgType.WELCOME
    await connection.deliver([WAMPMsgType.SUBSCRIBE, 1, {}, 'test.topic'])
    assert (await connection.receive())[0] == WAMPMsgType.SUBSCRIBED


def assert_cleaned_up(app):
    assert not app._active_sessions
    assert not app._subscription_exits
    assert not app._session_lifespan_exits


@pytest.mark.parametrize('say_goodbye', (False, True))
def test_cleanup_after_session_ends(async_support, backend, say_goodbye):
    events = []
    app = build_app(async_support, events)

    async def exercise():
        connection = StreamConnection()
        async with async_support.launch_task_group() as tasks:
            await tasks.spawn(app.handle_connection, connection)
            await subscribe(connection)
            if say_goodbye:
                await connection.deliver([WAMPMsgType.GOODBYE, {},
                                          'wamp.close.close_realm'])
                reply = await connection.receive()
                assert reply[0] == WAMPMsgType.GOODBYE
            await connection.close()

    anyio.run(exercise, backend=backend)
    assert events == TORN_DOWN
    assert_cleaned_up(app)


def test_cleanup_when_cancelled(async_support, backend):
    events = []
    app = build_app(async_support, events)

    async def exercise():
        connection = StreamConnection()
        with anyio.fail_after(TIMEOUT):
            async with async_support.launch_task_group() as tasks:
                await tasks.spawn(app.handle_connection, connection)
                await subscribe(connection)
                await tasks.cancel()

    anyio.run(exercise, backend=backend)
    assert events == TORN_DOWN
    assert_cleaned_up(app)
