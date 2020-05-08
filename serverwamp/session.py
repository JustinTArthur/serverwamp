from abc import ABC, abstractmethod
from typing import Any, Iterable, Iterator

from serverwamp.adapters.async_base import AsyncTaskGroup
from serverwamp.protocol import (abort_msg, cra_challenge_msg,
                                 cra_challenge_string, event_msg,
                                 generate_global_id, goodbye_msg, scram_nonce,
                                 subscribed_response_msg, ticket_challenge_msg,
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
        connection,
        realm,
        tasks: AsyncTaskGroup,
        auth_id=None,
        auth_methods=()
    ):
        """Represents a WAMP session happening over a connection.
        The session is available to RPC and event topic routes.

        The session can be used to store information to be retrieved or changed
        by later effects:

            session['customer_id'] = 345

        """
        self.connection = connection

        self.id = generate_global_id()
        self.auth_id = auth_id
        self.auth_methods = auth_methods
        self.is_open = False
        self.realm = realm
        self.identity = NO_IDENTITY

        self._custom_state = {}
        self._said_goodbye = False
        self._subscriptions = {}
        self._subscriptions_ids = {}
        self._tasks = tasks
        self._authenticated = False

    def __getitem__(self, key: str) -> Any:
        return self._custom_state[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._custom_state[key] = value

    def __delitem__(self, key: str) -> None:
        del self._custom_state[key]

    def __len__(self) -> int:
        return len(self._custom_state)

    def __iter__(self) -> Iterator[str]:
        return iter(self._custom_state)

    async def spawn_task(self, fn, *fn_args, **fn_kwargs):
        await self._tasks.spawn(fn, *fn_args, **fn_kwargs)

    async def send_raw(self, msg: Iterable):
        await self.connection.send_msg(msg)

    async def send_event(self, topic, args=(), kwargs=None, trust_level=None):
        if topic not in self._subscriptions:
            return

        subscription_id = self._subscriptions[topic]
        msg = event_msg(
            subscription_id=subscription_id,
            publication_id=generate_global_id(),
            args=args,
            kwargs=kwargs,
            trust_level=trust_level
        )
        await self.connection.send_msg(msg)

    async def request_ticket_authentication(self):
        await self.connection.send_msg(ticket_challenge_msg())

    async def request_cra_auth(self, auth_role: str, auth_provider: str):
        challenge_string = cra_challenge_string(
            self.id,
            auth_id=self.auth_id,
            auth_provider=auth_role,
            auth_role=auth_provider,
            nonce=scram_nonce()
        )
        await self.connection.send_msg(cra_challenge_msg(challenge_string))

    async def register_subscription(self, topic_uri: str) -> int:
        sub_id = self.subscription_id_for_topic(topic_uri)
        self._subscriptions[topic_uri] = sub_id
        self._subscriptions_ids[sub_id] = topic_uri
        return sub_id

    async def unregister_subscription(self, sub_id: int):
        topic_uri = self._subscriptions_ids.pop(sub_id)
        if not topic_uri:
            "wamp.error.no_such_subscription"
        del self._subscriptions[topic_uri]

    async def mark_subscribed(self, request, subscription_id: int):
        await self.connection.send_msg(
            subscribed_response_msg(request, subscription_id)
        )

    @staticmethod
    def subscription_id_for_topic(topic):
        return hash(topic) & 0xFFFFFFFF

    async def mark_authenticated(self, identity: Any = None):
        if not self._authenticated:
            self._authenticated = True
            await self.connection.send_msg(welcome_msg(self.id))
            self.is_open = True
        self.identity = identity

    async def abort(self, uri=None, message=None):
        await self.connection.send_msg(abort_msg(uri, message))
        self._said_goodbye = True
        await self.close()

    async def close(self):
        if self.is_open and not self._said_goodbye:
            await self.connection.send_msg(goodbye_msg())
        self.is_open = False


class NoSuchSubscription(Exception):
    pass
