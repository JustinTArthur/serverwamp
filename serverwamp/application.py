from typing import Callable, Awaitable, Optional, Any, Iterable

from serverwamp.protocol import (WAMPGoodbyeRequest, WAMPRPCRequest,
                                 WAMPSubscribeRequest, WAMPUnsubscribeRequest)
from serverwamp.rpc import Router
from serverwamp.session import WAMPSession, NoSuchSubscription


class WAMPApplication:
    def __init__(self):
        self._router = Router()
        self._request_handlers = {
            WAMPGoodbyeRequest: WAMPApplication.default_goodbye_handler,
            WAMPRPCRequest: WAMPApplication.default_rpc_handler,
            WAMPSubscribeRequest: WAMPApplication.default_subscribe_handler,
            WAMPUnsubscribeRequest: WAMPApplication.default_unsubscribe_handler
        }

    async def default_session_handler(
        self,
        session: WAMPSession,
        transport_authenticator: Callable[[...], Awaitable] = None
    ):
        if transport_authenticator:
            session.user_identity = await transport_authenticator()
        await session.mark_authenticated()
        async for request in session.iterate_requests():
            self._request_handlers[type(request)](request)

    def set_default_rpc_arg(
        self,
        arg_name,
        value: Optional[Any] = None,
        factory: Optional[Callable] = None,
        realms: Optional[Iterable[str]] = None
    ) -> None:
        self._router.set_default_arg(arg_name, value, factory, realms)

    def add_rpc_routes(self, routes, realms=None):
        self._router.add_routes(routes, realms)

    async def default_rpc_handler(self, request):
        await self._router.handle_rpc_call(rpc_request=request)

    async def default_subscribe_handler(self, request):
        sub_id = await request.session.register_subscription(request.uri)
        await request.session.mark_subscribed(request, sub_id)

    async def default_unsubscribe_handler(self, request):
        try:
            await request.session.unregister_subscription(request.subscription)
        except NoSuchSubscription:
            await request.session.subscription

    async def default_goodbye_handler(self, request):
        await request.session.close()
