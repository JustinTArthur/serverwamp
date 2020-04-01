import asyncio
from contextlib import asynccontextmanager
from typing import Set

from serverwamp.adapters.async_base import AsyncSupport, AsyncTaskGroup

_schedule_in_loop = getattr(asyncio, 'create_task', asyncio.ensure_future)


class AsyncioAsyncSupport(AsyncSupport):
    @asynccontextmanager
    async def launch_task_group(self):
        task_group = AsyncioTaskGroup()
        try:
            yield task_group
            await task_group.wait()
        finally:
            await task_group.close()


class AsyncioTaskGroup(AsyncTaskGroup):
    def __init__(self):
        self._tasks: Set[asyncio.Task] = set()

    async def spawn(self, callback, *callback_args, **callback_kwargs):
        coro_obj = callback(*callback_args, **callback_kwargs)
        task = _schedule_in_loop(coro_obj)
        task.add_done_callback(self._tasks.remove)
        self._tasks.add(task)

    async def cancel(self):
        while self._tasks:
            task = self._tasks.pop()
            if not task.done():
                task.cancel()

    async def wait(self):
        await asyncio.gather(*self._tasks)

    async def close(self):
        await self.cancel()
