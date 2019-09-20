import enum
from typing import Any, Callable, Iterable, Optional

from serverwamp.rpc import Router


@enum.unique
class IncidentType(enum.Enum):
    AUTHENTICATION_FAILED = enum.auto()


default_incident_uris = {
    IncidentType.AUTHENTICATION_FAILED: 'wamp.error.not_authorized'
}


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
