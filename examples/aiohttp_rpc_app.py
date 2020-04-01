import asyncio

from aiohttp import web
from serverwamp import WAMPApplication
from serverwamp.rpc import RPCRouteSet

simple_api = RPCRouteSet()


@simple_api.route('say_hello')
async def say_hello():
    return 'hello',


@simple_api.route('delayed_echo')
async def delayed_echo(value: str, delay: float = 0):
    await asyncio.sleep(delay)
    return value,


if __name__ == '__main__':
    wamp = WAMPApplication()
    wamp.add_rpc_routes(simple_api)

    app = web.Application()
    app.add_routes(
        web.get('/', wamp.aiohttp_websocket_handler()),
    )
    web.run_app(app)

