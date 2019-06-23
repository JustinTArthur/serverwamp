import asyncio
from decimal import Decimal

from serverwamp import rpc
from serverwamp.protocol import (WAMPRPCErrorResponse, WAMPRPCRequest,
                                 WAMPRPCResponse, WAMPSession)


def test_route_table():
    route_table = rpc.RPCRouteTableDef()

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

    router = rpc.Router()
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

    router = rpc.Router()
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
