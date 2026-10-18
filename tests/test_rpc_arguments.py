import asyncio
from typing import Any

import pytest

import serverwamp
from serverwamp.protocol import WAMPMsgType
from serverwamp.rpc import RPCErrorResult, RPCRequest, RPCResult, RPCRouter

from memory_connection import TIMEOUT, MemoryConnection, run


def call(procedure, args=(), kwargs=None, default_args=None):
    router = RPCRouter()
    for name, value in (default_args or {}).items():
        router.set_default_arg(name, value)
    router.add_route('procedure', procedure)
    request = RPCRequest(1, 'the session', 'procedure', list(args), kwargs or {})

    async def results():
        return [result async for result in router.handle_rpc_call(request)]

    (result,) = run(results())
    return result


def returning_args(*args, **kwargs):
    return RPCResult(args=args, kwargs=kwargs)


@pytest.mark.parametrize('args, kwargs, expected', (
    (['joe'], {}, RPCResult(args=('joe', 20))),
    (['joe'], {'limit': 5}, RPCResult(args=('joe', 5))),
    ([], {'query': 'joe', 'limit': '5'}, RPCResult(args=('joe', 5))),
))
def test_keyword_only_params(args, kwargs, expected):
    async def procedure(query, *, limit: int = 20):
        return returning_args(query, limit)

    assert call(procedure, args, kwargs) == expected


def test_keyword_only_param_required():
    async def procedure(*, query):
        return returning_args(query)

    assert call(procedure, kwargs={'query': 'joe'}) == RPCResult(args=('joe',))
    result = call(procedure)
    assert isinstance(result, RPCErrorResult)
    assert result.error_uri == 'wamp.error.invalid_argument'


def test_var_positional_param_gets_remaining_args():
    async def procedure(first, *rest: int, session):
        return returning_args(first, rest, session)

    assert call(procedure, ['a', '1', 2]) == RPCResult(args=('a', (1, 2), 'the session'))
    assert call(procedure, ['a']) == RPCResult(args=('a', (), 'the session'))


def test_var_keyword_param_gets_remaining_kwargs():
    async def procedure(name, session, **options):
        return returning_args(name, options)

    result = call(procedure, ['joe'], {'name': 'ignored', 'session': 'ignored', 'color': 'red'})
    assert result == RPCResult(args=('joe', {'color': 'red'}))


def test_var_params_without_request_values():
    async def procedure(*args, **kwargs):
        return returning_args(args, kwargs)

    assert call(procedure) == RPCResult(args=((), {}))


def test_default_args_not_taken_from_request():
    async def procedure(db, user_id: int, new_name: str, session):
        return returning_args(db, user_id, new_name, session)

    expected = RPCResult(args=('server db', 42, 'Ada', 'the session'))
    default_args = {'db': 'server db'}
    assert call(procedure, [42, 'Ada'], default_args=default_args) == expected
    assert call(
        procedure,
        kwargs={'db': 'client db', 'user_id': 42, 'new_name': 'Ada'},
        default_args=default_args
    ) == expected


def invalid_argument(message):
    return RPCErrorResult(
        error_uri='wamp.error.invalid_argument',
        kwargs={'message': message}
    )


@pytest.mark.parametrize('args, kwargs, message', (
    (['x'], {}, 'Argument user_id is not a valid int.'),
    ([], {'user_id': 'x'}, 'Argument user_id is not a valid int.'),
    ([1, 'x'], {}, 'Argument scores is not a valid float.'),
    ([1], {'color': 'x'}, 'Argument color is not a valid int.'),
    ([[1]], {}, 'Argument user_id is not a valid int.'),
))
def test_unconvertible_args_are_invalid(args, kwargs, message):
    async def procedure(user_id: int, *scores: float, **options: int):
        raise AssertionError('Called with an invalid argument.')

    assert call(procedure, args, kwargs) == invalid_argument(message)


def test_param_defaults_not_converted():
    async def procedure(limit: int = None, *, offset: int = None):  # type: ignore[assignment]
        return returning_args(limit, offset)

    assert call(procedure) == RPCResult(args=(None, None))
    assert call(procedure, ['5'], {'offset': '2'}) == RPCResult(args=(5, 2))


@pytest.mark.parametrize('annotation', (int | None, list[int], Any, 'int'))
def test_non_class_annotations_not_converted(annotation):
    async def procedure(value):
        return returning_args(value)
    procedure.__annotations__['value'] = annotation

    assert call(procedure, ['5']) == RPCResult(args=('5',))
    assert call(procedure, [None]) == RPCResult(args=(None,))


def test_invalid_argument_error_message():
    routes = serverwamp.RPCRouteSet()

    @routes.route('procedure')
    async def procedure(user_id: int):
        raise AssertionError('Called with an invalid argument.')

    app = serverwamp.Application()
    app.add_rpc_routes(routes)

    async def exercise():
        connection = MemoryConnection()
        handling = asyncio.ensure_future(app.handle_connection(connection))
        connection.inbound.put_nowait([WAMPMsgType.HELLO, 'test.realm', {}])
        assert (await connection.receive())[0] == WAMPMsgType.WELCOME
        connection.inbound.put_nowait([WAMPMsgType.CALL, 1, {}, 'procedure', ['x']])
        error = await connection.receive()
        await connection.close()
        await asyncio.wait_for(handling, TIMEOUT)
        return error

    assert list(run(exercise())) == [
        WAMPMsgType.ERROR, WAMPMsgType.CALL, 1, {}, 'wamp.error.invalid_argument',
        (), {'message': 'Argument user_id is not a valid int.'}
    ]
