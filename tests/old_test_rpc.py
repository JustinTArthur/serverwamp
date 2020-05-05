import asyncio
from decimal import Decimal
from unittest.mock import Mock

import pytest

from serverwamp import rpc
from serverwamp.protocol import (WAMPRPCErrorResponse, WAMPRPCRequest,
                                 WAMPRPCResponse, WAMPSession)


def test_route_table():
    route_table = rpc.RPCRouteSet()

    @route_table.route('sample.uri.1')
    async def sample_handler_1():
        pass

    @route_table.route('sample.uri.2')
    async def sample_handler_2():
        pass

    assert len(route_table) == 2

    assert route_table[1].handler == sample_handler_2
    assert route_table[1].uri == 'sample.uri.2'


def test_router_rpc_handling():
    loop = asyncio.get_event_loop()

    async def sample_handler(arg1):
        return {'kwarg1': 1337, 'kwargs2': 'Test.', 'requestArg1': arg1}

    async def error_handler():
        raise rpc.RPCError(
            'wamp.error.sample_error_uri',
            {'reason': "It just didn't work out."}
        )

    router = rpc.RPCRouter()
    router.add_routes((
        rpc.route('sample.uri', sample_handler),
        rpc.route('sample.uri.with_error', error_handler)
    ))

    request = WAMPRPCRequest(
        WAMPSession(1),
        1,
        {},
        'sample.uri',
        ['testArgValue']
    )
    response = loop.run_until_complete(router.handle_rpc_call(request))
    assert isinstance(response, WAMPRPCResponse)
    assert response.request is request
    assert len(response.args) == 0
    assert response.kwargs == {
        'kwarg1': 1337,
        'kwargs2': 'Test.',
        'requestArg1': 'testArgValue'
    }

    request = WAMPRPCRequest(WAMPSession(1), 2, {}, 'sample.uri.with_error')
    response = loop.run_until_complete(router.handle_rpc_call(request))
    assert isinstance(response, WAMPRPCErrorResponse)
    assert response.request is request
    assert response.uri == 'wamp.error.sample_error_uri'
    assert response.kwargs == {'reason': "It just didn't work out."}


def test_type_marshaling():
    async def typed_rpc_handler(
        a_decimal: Decimal,
        a_string: str,
        an_integer_w_default: int = 45
    ):
        return {
            'string_plus_suffix': f'{a_string}_test_suffix',
            'decimal_plus_int': a_decimal + an_integer_w_default
        }

    router = rpc.RPCRouter()
    router.add_routes((
        rpc.route('test_route', typed_rpc_handler),
    ))
    # Try with args:
    passthrough_request = WAMPRPCRequest(
        WAMPSession(1),
        1,
        {},
        'test_route',
        (1234.56, 'test_string')
    )
    coercion_request = WAMPRPCRequest(
        WAMPSession(1),
        2,
        {},
        'test_route',
        ('1234.56', 'another_test_string')
    )
    kwargs_request = WAMPRPCRequest(
        WAMPSession(1),
        3,
        {},
        'test_route',
        kwargs={
            'a_decimal': 42.0,
            'a_string': 'kwargs_test_string'
        }
    )
    loop = asyncio.get_event_loop()
    passthrough_response = loop.run_until_complete(
        router.handle_rpc_call(passthrough_request)
    )
    coercion_response = loop.run_until_complete(
        router.handle_rpc_call(coercion_request)
    )
    kwargs_response = loop.run_until_complete(
        router.handle_rpc_call(kwargs_request)
    )
    assert passthrough_response.kwargs == {
        'string_plus_suffix': 'test_string_test_suffix',
        'decimal_plus_int': Decimal(1234.56) + 45,
    }
    assert coercion_response.kwargs == {
        'string_plus_suffix': 'another_test_string_test_suffix',
        'decimal_plus_int': Decimal('1279.56'),
    }
    assert kwargs_response.kwargs == {
        'string_plus_suffix': 'kwargs_test_string_test_suffix',
        'decimal_plus_int': Decimal(42.0) + 45,
    }


def test_default_args():
    collected_arg_values = []

    async def rpc_handler(request, factory_default, value_default):
        collected_arg_values.append(factory_default)
        collected_arg_values.append(value_default)

    router = rpc.RPCRouter()
    router.add_routes((
        rpc.route('test_route', rpc_handler),
    ))

    factory_result = object()
    factory = Mock(return_value=factory_result)
    value_arg = object()

    router.set_default_arg('factory_default', factory=factory)
    router.set_default_arg('value_default', value_arg)
    request = WAMPRPCRequest(WAMPSession(1), 1, {}, 'test_route')

    loop = asyncio.get_event_loop()
    loop.run_until_complete(router.handle_rpc_call(request))
    assert factory.call_count == 1
    assert collected_arg_values[0] is factory_result
    assert collected_arg_values[1] is value_arg


def test_realms():
    route_set = rpc.RPCRouteSet()
    router = rpc.RPCRouter()

    async def any_realm_handler():
        pass
    any_realm_handler = Mock(wraps=any_realm_handler)

    async def specific_realm_handler():
        pass
    specific_realm_handler = Mock(wraps=specific_realm_handler)

    route_set.route(any_realm_handler)
    router.add_route(
        'any_realm_handler',
        any_realm_handler
    )
    router.add_route(
        'specific_realm_handler',
        specific_realm_handler,
        realms=('realm1',)
    )

    loop = asyncio.get_event_loop()

    realm1_session = WAMPSession(1, realm='realm1')
    realm1_specific_call = rpc.WAMPRPCRequest(
        realm1_session,
        1,
        {},
        'specific_realm_handler',
    )
    loop.run_until_complete(
        router.handle_rpc_call(realm1_specific_call)
    )
    realm1_any_call = rpc.WAMPRPCRequest(
        realm1_session,
        2,
        {},
        'any_realm_handler',
    )
    loop.run_until_complete(
        router.handle_rpc_call(realm1_any_call)
    )

    realm2_session = WAMPSession(2, realm='realm2')
    realm2_specific_realm1_call = rpc.WAMPRPCRequest(
        realm2_session,
        1,
        {},
        'specific_realm_handler',
    )
    with pytest.raises(rpc.WAMPNoSuchProcedureError):
        loop.run_until_complete(
            router.handle_rpc_call(realm2_specific_realm1_call)
        )
    realm2_any_call = rpc.WAMPRPCRequest(
        realm2_session,
        1,
        {},
        'any_realm_handler',
    )
    loop.run_until_complete(
        router.handle_rpc_call(realm2_any_call)
    )
