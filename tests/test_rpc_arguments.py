import pytest

from serverwamp.rpc import RPCErrorResult, RPCRequest, RPCResult, RPCRouter

from memory_connection import run


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
