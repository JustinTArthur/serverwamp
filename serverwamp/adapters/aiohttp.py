import asyncio
from asyncio import Task
from typing import Set

from aiohttp import WSMsgType, web
from serverwamp.adapters import base
from serverwamp.protocol import WAMPProtocol

get_event_loop = getattr(asyncio, 'get_running_loop', asyncio.get_event_loop)


class WSTransport(base.Transport):
    """Transport for WAMPProtocol objects for sending messages across an aiohttp
    WebSocketResponse."""
    def __init__(
        self,
        request: web.Request,
        ws_response: web.WebSocketResponse,
    ) -> None:
        self.closed = False
        self.request = request
        self._loop = get_event_loop()
        self._scheduled_tasks: Set[Task] = set()
        self._ws = ws_response

    @property
    def remote(self):
        return self.request.remote

    @property
    def cookies(self):
        return self.request.cookies

    def send_msg_soon(self, msg):
        """Send a message to the WebSocket when the event loop gets a chance."""
        if self.closed:
            return
        task = self._loop.create_task(self._ws.send_str(msg))
        self._scheduled_tasks.add(task)
        task.add_done_callback(self._scheduled_tasks.remove)

    async def send_msg(self, msg):
        """Send a message to the WebSocket immediately, and block until the
        underlying send is complete."""
        if self.closed:
            return
        await self._ws.send_str(msg)

    async def close(self):
        self.closed = True
        await asyncio.gather(*self._scheduled_tasks)
        await self._ws.close()


class WAMPApplication(base.WAMPApplication):
    async def handle(self, request: web.Request):
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
                unsubscribe_handler=self.broker.handle_unsubscribe,
                **self._protocol_kwargs
            )
        else:
            wamp_protocol = WAMPProtocol(
                transport=transport,
                rpc_handler=self.router.handle_rpc_call,
                **self._protocol_kwargs
            )
        wamp_protocol.handle_websocket_open()

        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await wamp_protocol.handle_msg(msg.data)
            elif msg.type == WSMsgType.ERROR:
                print('ws connection closed with exception %s' % ws.exception())

        print('websocket connection closed')

        return ws