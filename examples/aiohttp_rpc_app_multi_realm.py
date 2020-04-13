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


async def customer_auth_handler(session):
    pass


if __name__ == '__main__':
    app = serverwamp.Application()
    customers_realm = app.create_realm('customers')
    customers_realm.add_rpc_routes(simple_api)

    admins = app.create_realm('admins')
    admins.add_transport_authenticator(customer_auth_handler)

    web_app = web.Application()
    web_app.add_routes((
        web.get('/', app.aiohttp_websocket_handler()),
    ))
    web.run_app(web_app)

