from contextlib import asynccontextmanager
from functools import partial

import trio
import trio_typing

from serverwamp.adapters.async_base import AsyncSupport, AsyncTaskGroup


class TrioAsyncSupport(AsyncSupport):
    @asynccontextmanager
    async def launch_task_group(self):
        async with trio.open_nursery() as nursery:
            task_group = TrioTaskGroup(nursery)
            yield task_group


class TrioTaskGroup(AsyncTaskGroup):
    """In Trio's case, this is just a light wrapper around Nursery."""
    def __init__(self, nursery: trio_typing.Nursery):
        self._nursery = nursery

    async def cancel(self):
        self._nursery.cancel_scope.cancel()

    async def spawn(self, callback, *callback_args, **callback_kwargs):
        if callback_kwargs:
            callback = partial(callback, **callback_kwargs)
        self._nursery.start_soon(callback, *callback_args)
