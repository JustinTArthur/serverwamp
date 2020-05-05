from abc import ABC, abstractmethod
from typing import Iterable, Sequence

from serverwamp.protocol import abort_msg


class Connection(ABC):
    """Manages a connection with a client that might support the WAMP protocol.
    Provides the application layer with messages from the underlying
    transport (serialization+communication), but does no WAMP protocol
    parsing or enforcement on them past packaging the messages. Intended to be
    subclassed for specific link/transport/presentation options, some which
    might employ 3rd-party libraries. Examples might be JSON-serialized
    WebSocket, a TCP connection using WAMP bytes transport, etc.
    """
    def __init__(self):
        self.transport_info = {}

    @abstractmethod
    async def iterate_msgs(self):
        # Read and present messages from the underlying transport.
        yield ()

    @abstractmethod
    async def send_msg(self, msg: Sequence):
        pass

    async def send_msgs(self, msgs: Iterable[Sequence]):
        """Send multiple messages to the underlying transport. For some
        transports, this might be overridden to take advantage of batching
        opportunities.
        """
        for msg in msgs:
            await self.send_msg(msg)

    @abstractmethod
    async def close(self):
        pass

    async def abort(self, reason_uri: str = "no_reason", msg: str = None):
        try:
            await self.send_msg(abort_msg(reason_uri, msg))
        finally:
            await self.close()
