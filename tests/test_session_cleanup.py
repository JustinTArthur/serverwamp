"""Checks that a session is cleaned up however it ends."""
import pytest
import trio

import serverwamp
from serverwamp.adapters.trio import TrioAsyncSupport
from serverwamp.connection import Connection
from serverwamp.protocol import WAMPMsgType

REALM_URI = 'test.realm'
TIMEOUT = 5.0
TORN_DOWN = ['state set up', 'subscribed', 'unsubscribed', 'state torn down']


class TrioMemoryConnection(Connection):
    def __init__(self):
        super().__init__()
        self._inbound_sender, self._inbound = trio.open_memory_channel(16)
        self._outbound_sender, self._outbound = trio.open_memory_channel(16)

    async def iterate_msgs(self):
        async for msg in self._inbound:
            yield msg

    async def send_msg(self, msg):
        await self._outbound_sender.send(msg)

    async def close(self):
        await self._inbound_sender.aclose()

    async def deliver(self, msg):
        await self._inbound_sender.send(msg)

    async def receive(self):
        with trio.fail_after(TIMEOUT):
            return await self._outbound.receive()


def build_app(async_support, events):
    async def session_state(session):
        events.append('state set up')
        yield
        events.append('state torn down')

    topics = serverwamp.TopicRouteSet()

    @topics.route('test.topic')
    async def subscription(topic_uri):
        events.append('subscribed')
        yield
        events.append('unsubscribed')

    realm = serverwamp.Realm(REALM_URI)
    realm.add_session_state_handler(session_state, authenticated_only=False)
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
    assert not app._session_state_exits


@pytest.mark.parametrize('say_goodbye', (False, True))
def test_cleanup_after_session_ends(say_goodbye):
    events = []
    app = build_app(TrioAsyncSupport, events)

    async def exercise():
        connection = TrioMemoryConnection()
        async with TrioAsyncSupport.launch_task_group() as tasks:
            await tasks.spawn(app.handle_connection, connection)
            await subscribe(connection)
            if say_goodbye:
                await connection.deliver([WAMPMsgType.GOODBYE, {},
                                          'wamp.close.close_realm'])
                reply = await connection.receive()
                assert reply[0] == WAMPMsgType.GOODBYE
            await connection.close()

    trio.run(exercise)
    assert events == TORN_DOWN
    assert_cleaned_up(app)


def test_cleanup_when_cancelled():
    events = []
    app = build_app(TrioAsyncSupport, events)

    async def exercise():
        connection = TrioMemoryConnection()
        with trio.fail_after(TIMEOUT):
            async with TrioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(app.handle_connection, connection)
                await subscribe(connection)
                await tasks.cancel()

    trio.run(exercise)
    assert events == TORN_DOWN
    assert_cleaned_up(app)
