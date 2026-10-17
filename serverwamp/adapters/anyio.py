from contextlib import asynccontextmanager
from functools import partial

import anyio
import anyio.abc

from serverwamp.adapters.async_base import AsyncSupport, AsyncTaskGroup


class AnyioAsyncSupport(AsyncSupport):
    @classmethod
    @asynccontextmanager
    async def launch_task_group(cls):
        async with anyio.create_task_group() as anyio_task_group:
            task_group = AnyioTaskGroup(anyio_task_group)
            yield task_group

    @classmethod
    async def shield(
        cls,
        callback,
        *callback_args,
        **callback_kwargs
    ):
        with anyio.CancelScope(shield=True):
            return await callback(*callback_args, **callback_kwargs)


class AnyioTaskGroup(AsyncTaskGroup):
    """In anyio's case, this is just a light wrapper around its own TaskGroup.
    """
    def __init__(self, anyio_task_group: anyio.abc.TaskGroup):
        self._anyio_task_group = anyio_task_group

    async def spawn(self, callback, *callback_args, **callback_kwargs):
        if callback_kwargs:
            callback = partial(callback, **callback_kwargs)
        self._anyio_task_group.start_soon(callback, *callback_args)

    async def cancel(self):
        self._anyio_task_group.cancel_scope.cancel()
