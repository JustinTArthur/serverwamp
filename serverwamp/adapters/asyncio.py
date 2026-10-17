import asyncio
from contextlib import asynccontextmanager

from serverwamp.adapters.async_base import AsyncSupport, AsyncTaskGroup


class AsyncioAsyncSupport(AsyncSupport):
    @classmethod
    @asynccontextmanager
    async def launch_task_group(cls):
        asyncio_task_group = asyncio.TaskGroup()
        task_group = AsyncioTaskGroup(asyncio_task_group)
        try:
            async with asyncio_task_group:
                yield task_group
        finally:
            # Tasks can still spawn others while the group waits on them.
            task_group._closed = True

    @classmethod
    async def shield(
        cls,
        callback,
        *callback_args,
        **callback_kwargs
    ):
        coro_obj = callback(*callback_args, **callback_kwargs)
        return await asyncio.shield(coro_obj)


class AsyncioTaskGroup(AsyncTaskGroup):
    """A light wrapper around asyncio's TaskGroup. Tasks are tracked here too,
    as TaskGroup can't cancel its tasks without failing.
    """
    def __init__(self, asyncio_task_group: asyncio.TaskGroup):
        self._asyncio_task_group = asyncio_task_group
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def spawn(self, callback, *callback_args, **callback_kwargs):
        coro_obj = callback(*callback_args, **callback_kwargs)
        try:
            task = self._asyncio_task_group.create_task(coro_obj)
        except RuntimeError:
            # Python 3.13+ already closes it, but earlier versions don't.
            coro_obj.close()
            if self._closed:
                raise
            # The group is shutting down after a failure, so as with trio and
            # anyio, the task is cancelled before it gets to run.
            return
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def cancel(self):
        for task in tuple(self._tasks):
            task.cancel()
