from contextlib import asynccontextmanager
from functools import partial

import anyio

from serverwamp.adapters.async_base import AsyncSupport, AsyncTaskGroup


class AnyioAsyncSupport(AsyncSupport):
    @asynccontextmanager
    async def launch_task_group(self):
        async with anyio.create_task_group() as anyio_task_group:
            task_group = AnyioTaskGroup(anyio_task_group)
            yield task_group


class AnyioTaskGroup(AsyncTaskGroup):
    """In anyio's case, this is just a light wrapper around its own TaskGroup.
    """
    def __init__(self, anyio_task_group: anyio.TaskGroup):
        self._anyio_task_group = anyio_task_group

    async def spawn(self, callback, *callback_args, **callback_kwargs):
        if callback_kwargs:
            callback = partial(callback, **callback_kwargs)

        await self._anyio_task_group.spawn(
            callback, *callback_args, **callback_kwargs
        )

    async def cancel(self):
        await self._anyio_task_group.cancel_scope.cancel()