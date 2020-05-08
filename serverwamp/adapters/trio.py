from functools import partial

import trio

from serverwamp.adapters.async_base import AsyncSupport, AsyncTaskGroup
from serverwamp.context import asynccontextmanager


class TrioAsyncSupport(AsyncSupport):
    @classmethod
    @asynccontextmanager
    async def launch_task_group(cls):
        async with trio.open_nursery() as nursery:
            task_group = TrioTaskGroup(nursery)
            yield task_group

    @classmethod
    async def shield(cls,
         callback,
         *callback_args,
         **callback_kwargs
    ):
        with trio.CancelScope() as cancel_scope:
            cancel_scope.shield = True


class TrioTaskGroup(AsyncTaskGroup):
    """In Trio's case, this is just a light wrapper around Nursery."""
    def __init__(self, nursery):
        self._nursery = nursery

    async def cancel(self):
        self._nursery.cancel_scope.cancel()

    async def spawn(self, callback, *callback_args, **callback_kwargs):
        if callback_kwargs:
            callback = partial(callback, **callback_kwargs)
        self._nursery.start_soon(callback, *callback_args)
