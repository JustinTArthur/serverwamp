"""An in-memory Connection for exercising Applications on any event loop
anyio supports.
"""
import anyio

from serverwamp.connection import Connection

TIMEOUT = 5.0


class StreamConnection(Connection):
    def __init__(self):
        super().__init__()
        self._inbound_sender, self._inbound = (
            anyio.create_memory_object_stream(16)
        )
        self._outbound_sender, self._outbound = (
            anyio.create_memory_object_stream(16)
        )

    async def iterate_msgs(self):
        async for msg in self._inbound:
            yield msg

    async def send_msg(self, msg):
        await self._outbound_sender.send(msg)

    async def close(self):
        await self._inbound_sender.aclose()

    async def deliver(self, msg):
        await self._inbound_sender.send(msg)

    async def receive(self):
        with anyio.fail_after(TIMEOUT):
            return await self._outbound.receive()
