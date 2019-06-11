import asyncio

from aiohttp import WSMsgType, web

from server_wamp.protocol import WAMPProtocol
from server_wamp.rpc import Router


class WSTransport:
    """Transport for WAMPProtocol objects for sending messages across an aiohttp
    WebSocketResponse."""
    def __init__(self, request, ws_response, loop=None):
        self.request = request
        self.ws = ws_response
        self.loop = loop or asyncio.get_event_loop()
        self.scheduled_tasks = set()
        self.closed = False

    async def close(self):
        self.closed = True
        for task in self.scheduled_tasks:
            task.cancel()
        await self.ws.close()

    @property
    def remote(self):
        return self.request.remote

    def schedule_msg(self, msg):
        """Send a message to the WebSocket when the event loop gets a chance."""
        if self.closed:
            return
        task = self.loop.create_task(self.ws.send_str(msg))
        self.scheduled_tasks.add(task)
        task.add_done_callback(self.scheduled_tasks.remove)

    async def send_msg(self, msg):
        """Send a message to the WebSocket immediately, and block until the
        underlying send is complete."""
        if self.closed:
            return
        await self.ws.send_str(msg)


class WAMPApplication:
    WS_PROTOCOLS = ('wamp.2.json',)

    def __init__(self, router=None, broker=None):
        self.router = router or Router()
        self.broker = broker

    async def handle(self, request):
        """Route handler for aiohttp server application. Any websocket routed to
        this handler will handled as a WAMP WebSocket
        """
        ws = web.WebSocketResponse(protocols=self.WS_PROTOCOLS)
        await ws.prepare(request)

        transport = WSTransport(request, ws)
        if self.broker:
            wamp_protocol = WAMPProtocol(
                transport=transport,
                rpc_handler=self.router.handle_rpc_call,
                subscribe_handler=self.broker.handle_subscribe,
                unsubscribe_handler=self.broker.handle_unsubscribe
            )
        else:
            wamp_protocol = WAMPProtocol(
                transport=transport,
                rpc_handler=self.router.handle_rpc_call
            )

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await wamp_protocol.handle_msg(msg.data)
            elif msg.type == WSMsgType.ERROR:
                print('ws connection closed with exception %s' % ws.exception())

        print('websocket connection closed')

        return ws

    def add_rpc_routes(self, routes):
        self.router.add_routes(routes)
