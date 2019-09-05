import asyncio
from typing import Awaitable, Callable, Mapping, Set

from serverwamp.adapters import asgi_base, base
from serverwamp.protocol import WAMPProtocol

get_event_loop = getattr(asyncio, 'get_running_loop', asyncio.get_event_loop)


class WSTransport(asgi_base.WSTransport):
    def __init__(
        self,
        loop,
        asgi_scope: Mapping,
        asgi_send: Callable[[Mapping], Awaitable]
    ) -> None:
        super().__init__(asgi_scope, asgi_send)
        self._loop = loop
        self._scheduled_tasks: Set[asyncio.Task] = set()

    def send_msg_soon(self, msg: str) -> None:
        task = self._loop.create_task(self.send_msg(msg))
        self._scheduled_tasks.add(task)
        task.add_done_callback(self._scheduled_tasks.remove)

    async def close(self):
        await asyncio.gather(*self._scheduled_tasks)
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

        transport = WSTransport(get_event_loop(), scope, send)
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
