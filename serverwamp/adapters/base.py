import enum
from abc import ABC, abstractmethod
from typing import Any, Callable, Iterable, Mapping, Optional

from serverwamp.rpc import Router


@enum.unique
class IncidentType(enum.Enum):
    AUTHENTICATION_FAILED = enum.auto()

default_incident_uris = {
    IncidentType.AUTHENTICATION_FAILED: 'wamp.error.not_authorized'
}


class Transport(ABC):
    @property
    def cookies(self) -> Optional[Mapping[str, str]]:
        return None

    @property
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
        self.incident_uris = default_incident_uris.copy()
        self._protocol_kwargs = protocol_kwargs

    def set_default_rpc_arg(
        self,
        arg_name,
        value: Optional[Any] = None,
        factory: Optional[Callable] = None,
        realms: Optional[Iterable[str]] = None
    ) -> None:
        self.router.set_default_arg(arg_name, value, factory, realms)

    def add_rpc_routes(self, routes, realms=None):
        self.router.add_routes(routes, realms)

    def set_incident_uri(self, incident_type: IncidentType, uri: str):
        self.incident_uris[incident_type] = uri
