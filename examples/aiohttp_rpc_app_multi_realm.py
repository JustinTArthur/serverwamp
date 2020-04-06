import asyncio
import serverwamp

from aiohttp import web

simple_api = serverwamp.RPCRouteSet()


@simple_api.route('say_hello')
async def say_hello():
    return 'hello',


@simple_api.route('delayed_echo')
async def delayed_echo(value: str, delay: float = 0):
    await asyncio.sleep(delay)
    return value,


async def customer_auth_handler(app, realm, session):
    pass


if __name__ == '__main__':
    customers = serverwamp.Realm('customers')
    customers.add_rpc_routes(simple_api)

    admins = serverwamp.Realm('admins')
    admins.set_auth_handler()

    app = serverwamp.Application()
    app.add_realm(wamp_realm)


    web_app = web.Application()
    web_app.add_routes((
        web.get('/', app.aiohttp_websocket_handler()),
    ))
    web.run_app(web_app)

