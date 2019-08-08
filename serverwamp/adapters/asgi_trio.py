from contextlib import AbstractAsyncContextManager
from typing import Awaitable, Callable, Mapping

import trio

from serverwamp.adapters import asgi_base, base
from serverwamp.protocol import WAMPProtocol


class WSTransport(asgi_base.WSTransport, AbstractAsyncContextManager):
    def __init__(
        self,
        asgi_scope: Mapping,
        asgi_send: Callable[[Mapping], Awaitable]
    ) -> None:
        super().__init__(asgi_scope, asgi_send)

    async def __aenter__(self):
        self._nursery = await trio.open_nursery().__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    def send_msg_soon(self, msg: str) -> None:
        self._nursery.start_soon(self.send_msg(msg))

    async def close(self):
        if self.closed:
            return
        await self._nursery.__aexit__()
        await super().close()


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

        async with trio.open_nursery() as nursery:
            transport = WSTransport(scope, send)
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

            while True:
                event = await receive()
                event_type = event['type']
                if event_type == 'websocket.receive':
                    msg_text = (
                        event.get('text')
                        or
                        event.get('data').decode('utf-8')
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
