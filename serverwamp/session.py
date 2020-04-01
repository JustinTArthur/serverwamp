from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncIterable, Iterable, Optional, Set

from serverwamp.adapters.async_base import AsyncTaskGroup
from serverwamp.protocol import (WAMPRequest, WAMPRPCRequest,
                                 WAMPSubscribeRequest, WAMPUnsubscribeRequest,
                                 abort_msg, cra_challenge_msg,
                                 cra_challenge_string, generate_global_id,
                                 goodbye_msg, subscribed_response_msg,
                                 welcome_msg)

NO_MORE_EVENTS = object()
NO_IDENTITY = object()


class AbstractAsyncQueue(ABC):
    @abstractmethod
    async def get(self) -> Any:
        pass

    @abstractmethod
    def task_done(self) -> None:
        pass

    def put_nowait(self, item: Any):
        pass


class WAMPSession:
    def __init__(
        self,
        transport,
        realm,
        tasks: AsyncTaskGroup,
        auth_id=None,
        auth_methods=()
    ):
        self.transport = transport

        self.id = generate_global_id()
        self.auth_id = auth_id
        self.auth_methods = auth_methods
        self.realm = realm
        self.user_identity = NO_IDENTITY
        self._request_queues: Set[AbstractAsyncQueue] = set()
        self._said_goodbye = False
        self._subscriptions = {}
        self._subscriptions_ids = {}
        self._tasks = tasks
        self._authenticated = False

    def spawn_task(self, fn, *fn_args, **fn_kwargs):
        self._tasks.spawn(fn, *fn_args, **fn_kwargs)

    async def send_raw(self, msg: Iterable):
        await self.transport.send_msg(msg)

    async def iterate_rpc_calls(self):
        async for req in self.iterate_requests():
            if isinstance(req, WAMPRPCRequest):
                yield req

    async def iterate_subs_and_unsubs(self):
        async for req in self.iterate_requests():
            if isinstance(req, (WAMPSubscribeRequest, WAMPUnsubscribeRequest)):
                yield req

    async def request_ticket_authentication(
        self,
        auth_id: str,
        auth_role: str,
        auth_provider: str,
        nonce: str,
        auth_time: Optional[datetime] = None
    ):
        challenge_string = cra_challenge_string(
            self.id,
            auth_id=auth_id,
            auth_provider=auth_provider,
            auth_role=auth_role,
            nonce=nonce,
            auth_time=auth_time
        )
        await self.transport.send_msg(cra_challenge_msg(challenge_string))

    async def request_cra_authentication(self):
        await self.transport.send_msg()

    async def register_subscription(self, topic_uri: str) -> int:
        sub_id = self.subscription_id_for_topic(topic_uri)
        self._subscriptions[topic_uri] = sub_id
        self._subscriptions_ids[sub_id] = topic_uri
        return sub_id

    async def unregister_subscription(self, sub_id: int):
        if sub_id not in self._subscriptions:
            "wamp.error.no_such_subscription"
        topic_uri = self._subscriptions_ids.pop(sub_id)

    async def mark_subscribed(self, request, subscription_id: int):
        await self.transport.send_msg(subscribed_response_msg(request, sub_id))

    @staticmethod
    def subscription_id_for_topic(topic):
        return hash(topic) & 0xFFFFFFFF

    async def mark_authenticated(self):
        if not self._authenticated:
            self._authenticated = True
            await self.transport.send_msg(welcome_msg(self.id))

    async def iterate_requests(self) -> AsyncIterable[WAMPRequest]:
        """Every call to this will asynchronously iterate the same requests
        coming from clients."""
        queue = self.transport.async_queue()
        self._request_queues.add(queue)
        try:
            while True:
                try:
                    request = await queue.get()
                    if request is NO_MORE_EVENTS:
                        break
                    yield request
                finally:
                    queue.task_done()
        finally:
            self._request_queues.remove(queue)

    async def abort(self, uri=None, message=None):
        await self.transport.send_msg(abort_msg(uri, message))
        self._said_goodbye = True
        await self.close()

    async def close(self):
        if not self._said_goodbye:
            await self.transport.send_msg(goodbye_msg())
        for queue in self._request_queues:
            queue.put_nowait(NO_MORE_EVENTS)

    async def handle_incoming_request(self, request: WAMPRequest):
        for queue in self._request_queues:
            queue.put_nowait(request)


class NoSuchSubscription(Exception):
    pass
