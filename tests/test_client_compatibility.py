"""Sessions as older WAMP clients conduct them, from the JSON they send."""
import asyncio
import json

import serverwamp
from serverwamp.protocol import WAMPMsgType

from memory_connection import TIMEOUT, MemoryConnection, run

REALM_URI = 'test.realm'


def test_ruby_wamp_client_0_0_x_session():
    """ruby wamp_client 0.0.x sends null authid and authmethods in HELLO
    when they aren't configured, uses random request IDs, and leaves empty
    arguments out of CALL.
    """
    topic_events = []
    rpc_routes = serverwamp.RPCRouteSet()
    topic_routes = serverwamp.TopicRouteSet()

    @rpc_routes.route('test.status')
    async def status():
        return 'ok',

    @topic_routes.route('test.topic')
    async def subscribe(topic_uri):
        topic_events.append('subscribed')
        yield
        topic_events.append('unsubscribed')

    async def exercise():
        connection = MemoryConnection()
        realm = serverwamp.Realm(REALM_URI)
        realm.add_rpc_routes(rpc_routes)
        realm.add_topic_routes(topic_routes)
        app = serverwamp.Application(allow_default_realm=False)
        app.add_realm(realm)
        handling = asyncio.ensure_future(app.handle_connection(connection))

        def send(msg_json):
            connection.inbound.put_nowait(json.loads(msg_json))

        send('[1, "test.realm", {"roles": {"caller": {"features": '
             '{"caller_identification": true}}, "subscriber": {}}, '
             '"agent": "Ruby-WampClient-0.0.2", "authid": null, '
             '"authmethods": null}]')
        welcome = await connection.receive()
        assert welcome[0] == WAMPMsgType.WELCOME

        send('[32, 7149173219735043, {}, "test.topic"]')
        subscribed = await connection.receive()
        assert subscribed[:2] == (WAMPMsgType.SUBSCRIBED, 7149173219735043)
        sub_id = subscribed[2]

        send('[48, 0, {}, "test.status"]')
        result = await connection.receive()
        assert result[:2] == (WAMPMsgType.CALL_RESULT, 0)

        send('[32, 912, {}, "test.topic"]')
        assert await connection.receive() == (
            WAMPMsgType.SUBSCRIBED, 912, sub_id
        )

        send(f'[34, 85346237, {sub_id}]')
        assert await connection.receive() == (WAMPMsgType.UNSUBSCRIBED,
                                              85346237)

        send('[6, {"message": "user initiated"}, "wamp.close.normal"]')
        goodbye = await connection.receive()
        assert goodbye[0] == WAMPMsgType.GOODBYE
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)

    run(exercise())
    assert topic_events == ['subscribed', 'unsubscribed']
