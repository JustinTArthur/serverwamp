import asyncio

from server_wamp import rpc
from server_wamp.protocol import (WAMPRPCErrorResponse, WAMPRPCRequest,
                                  WAMPRPCResponse)


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
        1,
        1,
        '192.168.1.101',
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

    request = WAMPRPCRequest(1, 1, '192.168.1.101', {}, 'sample.uri.with_error')
    response = loop.run_until_complete(router.handle_rpc_call(request))
    assert isinstance(response, WAMPRPCErrorResponse)
    assert response.request is request
    assert response.uri == 'wamp.error.sample_error_uri'
    assert response.kwargs == {'reason': "It just didn't work out."}
