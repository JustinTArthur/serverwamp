from abc import ABC, abstractmethod
from typing import Mapping, Optional

from serverwamp.rpc import Router


class Transport(ABC):
    @property
    @abstractmethod
    def cookies(self) -> Optional[Mapping[str, str]]:
        return None

    @property
    @abstractmethod
    def remote(self):
        return None

    @abstractmethod
    def send_msg_soon(self, msg: str) -> None:
        """Send a serialized message to the underlying transport at some point
        soon. Returns immediately without awaiting any kind of send
        confirmation."""
        pass

    @abstractmethod
    async def send_msg(self, msg: str) -> None:
        """Send a message to the underlying transport immediately, and block
        until the underlying send is complete.
        """
        pass

    @abstractmethod
    async def close(self):
        """Close the underlying transport as soon as any scheduled tasks
        are complete."""
        pass


class WAMPApplication:
    WS_PROTOCOLS = ('wamp.2.json',)

    def __init__(self, router=None, broker=None, **protocol_kwargs):
        self.router = router or Router()
        self.broker = broker
        self._protocol_kwargs = protocol_kwargs

    def add_rpc_routes(self, routes):
        self.router.add_routes(routes)
