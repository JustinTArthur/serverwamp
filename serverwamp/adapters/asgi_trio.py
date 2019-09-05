from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Mapping

import trio

from serverwamp.adapters import asgi_base, base
from serverwamp.protocol import WAMPProtocol


class WSTransport(asgi_base.WSTransport):
    def __init__(
        self,
        nursery,
        asgi_scope: Mapping,
        asgi_send: Callable[[Mapping], Awaitable]
    ) -> None:
        super().__init__(asgi_scope, asgi_send)
        self._nursery = nursery

    def send_msg_soon(self, msg: str) -> None:
        self._nursery.start_soon(self.send_msg(msg))

    async def close(self):
        if self.closed:
            return
        await super().close()


@asynccontextmanager
async def managed_ws_transport(asgi_scope, asgi_send):
    try:
        async with trio.open_nursery() as transport_nursery:
            transport = WSTransport(transport_nursery, asgi_scope, asgi_send)
            yield transport
    finally:
        await transport.close()


class WAMPApplication(base.WAMPApplication):
    async def asgi_application(
        self,
        scope: Mapping,
        receive: Callable[[], Awaitable[Mapping]],
        send: Callable[[Mapping], Awaitable]
    ) -> None:
        if scope['type'] != 'websocket':
            raise Exception(f'Connection scope "{type}" not supported by this '
                            'ASGI adapter.')

        async with managed_ws_transport(scope, send) as transport:
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
                    transport_authenticator=None,
                    rpc_handler=self.router.handle_rpc_call,
                    **self._protocol_kwargs
                )

            await send({
                'type': 'websocket.accept',
                'subprotocol': self.WS_PROTOCOLS[0]
            })

            while not transport.closed:
                event = await receive()
                event_type = event['type']
                if event_type == 'websocket.receive':
                    msg_text = (
                        event.get('text')
                        or
                        event['data'].decode('utf-8')
                    )
                    await wamp_protocol.handle_msg(msg_text)
                elif event_type == 'websocket.disconnect':
                    break

    def legacy_asgi_application(
        self,
        scope: Mapping
    ) -> Callable[
        [
            Callable[[], Awaitable[Mapping]],
            Callable[[Mapping], Awaitable]
        ],
        Awaitable
    ]:
        if scope['type'] != 'websocket':
            raise Exception(f'Connection scope "{type}" not supported by this '
                            f'ASGI adapter.')

        async def _legacy_asgi_app_awaitable(
            receive: Callable[[], Awaitable[Mapping]],
            send: Callable[[Mapping], Awaitable]
        ) -> None:
            return await self.asgi_application(scope, receive, send)

        return _legacy_asgi_app_awaitable
