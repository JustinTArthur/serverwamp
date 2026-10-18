import asyncio

import pytest

import serverwamp
from serverwamp.protocol import WAMPMsgType

from memory_connection import TIMEOUT, MemoryConnection, run


def routes_answering(answer):
    routes = serverwamp.RPCRouteSet()

    @routes.route('which_realm')
    async def which_realm():
        return answer,

    return routes


def build_app(**app_kwargs):
    app = serverwamp.Application(**app_kwargs)
    explicit_realm = serverwamp.Realm('explicit.realm')
    explicit_realm.add_rpc_routes(routes_answering('explicit'))
    app.add_realm(explicit_realm)
    if app_kwargs.get('allow_default_realm', True):
        app.add_rpc_routes(routes_answering('default'))
    return app


async def say_hello(app, realm_uri):
    connection = MemoryConnection()
    handling = asyncio.ensure_future(app.handle_connection(connection))
    connection.inbound.put_nowait([WAMPMsgType.HELLO, realm_uri, {}])
    reply = await connection.receive()
    return connection, handling, reply


async def call_which_realm(app, realm_uri):
    connection, handling, welcome = await say_hello(app, realm_uri)
    assert welcome[0] == WAMPMsgType.WELCOME

    connection.inbound.put_nowait([WAMPMsgType.CALL, 1, {}, 'which_realm'])
    result = await connection.receive()
    assert result[0] == WAMPMsgType.CALL_RESULT

    await connection.close()
    await asyncio.wait_for(handling, TIMEOUT)
    return result[3]


def test_unconfigured_realm_uses_default_realm():
    app = build_app()
    assert run(call_which_realm(app, 'unconfigured.realm')) == ('default',)


def test_configured_realm_takes_precedence_over_default_realm():
    app = build_app()
    assert run(call_which_realm(app, 'explicit.realm')) == ('explicit',)


def test_unconfigured_realm_aborted_without_default_realm():
    app = build_app(allow_default_realm=False)

    async def exercise():
        connection, handling, abort = await say_hello(app, 'unconfigured.realm')
        await asyncio.wait_for(handling, TIMEOUT)
        return abort

    abort = run(exercise())
    assert abort[0] == WAMPMsgType.ABORT
    assert abort[2] == 'wamp.error.no_such_realm'


def test_configured_realm_works_without_default_realm():
    app = build_app(allow_default_realm=False)
    assert run(call_which_realm(app, 'explicit.realm')) == ('explicit',)


async def _noop(*args, **kwargs):
    pass


@pytest.mark.parametrize('method_name, args', (
    ('set_authentication_handler', (_noop,)),
    ('set_rpc_handler', (_noop,)),
    ('set_subscription_handler', (_noop,)),
    ('add_transport_authenticator', (_noop,)),
    ('set_cra_handlers', (_noop, _noop)),
    ('set_ticket_authenticator', (_noop,)),
    ('add_session_lifespan', (_noop,)),
    pytest.param('add_session_state_handler', (_noop,),
                 marks=pytest.mark.filterwarnings('ignore::DeprecationWarning')),
    ('set_default_arg', ('arg_name', 'value')),
    ('add_rpc_routes', (serverwamp.RPCRouteSet(),)),
    ('add_topic_routes', (serverwamp.TopicRouteSet(),)),
))
def test_default_realm_config_without_default_realm(method_name, args):
    app = serverwamp.Application(allow_default_realm=False)
    with pytest.raises(RuntimeError, match='allow_default_realm=False'):
        getattr(app, method_name)(*args)


def test_deprecated_session_state_handler_names():
    realm = serverwamp.Realm('test.realm')
    with pytest.warns(DeprecationWarning, match='add_session_lifespan'):
        realm.add_session_state_handler(_noop)
    with pytest.warns(DeprecationWarning, match='add_session_lifespan'):
        realm.add_session_state_handler(_noop, authenticated_only=False)
    with pytest.warns(DeprecationWarning, match='authed_session_lifespans'):
        assert realm.authed_session_state_handlers == [_noop]
    with pytest.warns(DeprecationWarning, match='session_lifespans'):
        assert realm.session_state_handlers == [_noop]
    assert realm.authed_session_lifespans == realm.session_lifespans == [_noop]

    app = serverwamp.Application()
    with pytest.warns(DeprecationWarning, match='add_session_lifespan'):
        app.add_session_state_handler(_noop)
    assert app._default_realm.authed_session_lifespans == [_noop]

    with pytest.warns(DeprecationWarning, match='SessionLifespan'):
        from serverwamp.application import SessionStateHandler
    assert SessionStateHandler is serverwamp.application.SessionLifespan
