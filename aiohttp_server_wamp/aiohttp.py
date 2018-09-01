from aiohttp import WSMsgType, web

from .helpers import camel_to_snake
from .protocol import WAMPProtocol
from .rpc import Router


class WampApplication:
    WS_PROTOCOLS = ('wamp.2.json',)

    def __init__(self):
        self.router = Router()

    async def handle(self, request):
        """Route handler for aiohttp server application. Any websocket routed to
        this handler will handled as a WAMP WebSocket
        """
        ws = web.WebSocketResponse(protocols=self.WS_PROTOCOLS)
        await ws.prepare(request)
        wamp_protocol = WAMPProtocol(transport=ws, rpc_handler=self._handle_rpc_call)

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await wamp_protocol.handle_msg(msg.data)
            elif msg.type == WSMsgType.ERROR:
                print('ws connection closed with exception %s' % ws.exception())

        print('websocket connection closed')

        return ws

    def add_rpc_routes(self, routes):
        self.router.add_routes(routes)

    async def _handle_rpc_call(self, uri, args, kwargs):
        command = self.router.resolve(uri)
        kwargs = {camel_to_snake(k): v for k, v in kwargs}
        return command(*args, **kwargs)
