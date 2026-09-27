"""An in-memory Connection for exercising Applications in tests."""
import asyncio

from serverwamp.connection import Connection

TIMEOUT = 5.0


class MemoryConnection(Connection):
    def __init__(self):
        super().__init__()
        self.inbound = asyncio.Queue()
        self.outbound = asyncio.Queue()

    async def iterate_msgs(self):
        while True:
            msg = await self.inbound.get()
            if msg is None:
                return
            yield msg

    async def send_msg(self, msg):
        await self.outbound.put(msg)

    async def close(self):
        self.inbound.put_nowait(None)

    async def receive(self):
        return await asyncio.wait_for(self.outbound.get(), TIMEOUT)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
