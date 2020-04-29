from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Iterable, Optional

from serverwamp.adapters.async_base import AsyncTaskGroup
from serverwamp.protocol import (abort_msg, cra_challenge_msg,
                                 cra_challenge_string, event_msg,
                                 generate_global_id, goodbye_msg,
                                 subscribed_response_msg, welcome_msg)

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
        connection,
        realm,
        tasks: AsyncTaskGroup,
        auth_id=None,
        auth_methods=()
    ):
        self.connection = connection

        self.id = generate_global_id()
        self.auth_id = auth_id
        self.auth_methods = auth_methods
        self.realm = realm
        self.user_identity = NO_IDENTITY
        self._said_goodbye = False
        self._subscriptions = {}
        self._subscriptions_ids = {}
        self._tasks = tasks
        self._authenticated = False

    def spawn_task(self, fn, *fn_args, **fn_kwargs):
        self._tasks.spawn(fn, *fn_args, **fn_kwargs)

    async def send_raw(self, msg: Iterable):
        await self.connection.send_msg(msg)

    async def send_event(self, topic, args=(), kwargs=None, trustlevel=None):
        if topic not in self._subscriptions:
            return

        subscription_id = self._subscriptions[topic]
        msg = event_msg(
            subscription_id=subscription_id,
            publication_id=generate_global_id(),
            args=args,
            kwargs=kwargs
        )
        await self.connection.send_msg(msg)

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
        await self.connection.send_msg(cra_challenge_msg(challenge_string))

    async def request_cra_authentication(self):
        await self.connection.send_msg()

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
        await self.connection.send_msg(subscribed_response_msg(request, subscription_id))

    @staticmethod
    def subscription_id_for_topic(topic):
        return hash(topic) & 0xFFFFFFFF

    async def mark_authenticated(self):
        if not self._authenticated:
            self._authenticated = True
            await self.connection.send_msg(welcome_msg(self.id))

    async def abort(self, uri=None, message=None):
        await self.connection.send_msg(abort_msg(uri, message))
        self._said_goodbye = True
        await self.close()

    async def close(self):
        if not self._said_goodbye:
            await self.connection.send_msg(goodbye_msg())


class NoSuchSubscription(Exception):
    pass
