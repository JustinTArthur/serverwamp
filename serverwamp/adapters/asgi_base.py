from abc import ABC
from http.cookies import CookieError, SimpleCookie
from typing import Awaitable, Callable, Mapping, Optional

from serverwamp.protocol import Transport


class WSTransport(Transport, ABC):
    def __init__(
        self,
        asgi_scope: Mapping,
        asgi_send: Callable[[Mapping], Awaitable]
    ) -> None:
        self.closed = False
        self._asgi_send = asgi_send
        self._remote: Optional[str]

        cookies_header = asgi_scope['headers'].get(b'Cookie')
        if cookies_header:
            try:
                cookie = SimpleCookie(cookies_header)
            except CookieError:
                self._cookies = None
            else:
                self._cookies = {k: v.value for k, v in cookie.items()}
        if 'client' in asgi_scope:
            self._remote = str(tuple(asgi_scope['client']))
        else:
            self._remote = None

    @property
    def cookies(self) -> Optional[Mapping[str, str]]:
        return self._cookies

    @property
    def remote(self):
        return self._remote

    async def send_msg(self, msg: str) -> None:
        if self.closed:
            return
        await self._asgi_send({
            'type': 'websocket.send',
            'text': msg
        })

    async def close(self):
        if self.closed:
            return
        self.closed = True
        await self._asgi_send({'type': 'websocket.close'})
