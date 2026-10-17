import asyncio
import logging
from contextlib import asynccontextmanager
from typing import List, Set

from serverwamp.adapters.async_base import AsyncSupport, AsyncTaskGroup

logger = logging.getLogger(__name__)


class AsyncioAsyncSupport(AsyncSupport):
    @classmethod
    @asynccontextmanager
    async def launch_task_group(cls):
        task_group = AsyncioTaskGroup()
        try:
            yield task_group
            await task_group.wait()
        finally:
            await task_group.close()

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
    def __init__(self):
        self._tasks: Set[asyncio.Task] = set()
        self._errors: List[BaseException] = []

    async def spawn(self, callback, *callback_args, **callback_kwargs):
        coro_obj = callback(*callback_args, **callback_kwargs)
        task = asyncio.create_task(coro_obj)
        task.add_done_callback(self._task_done)
        self._tasks.add(task)
        if self._errors:
            # The group already failed, so the task won't get to run.
            task.cancel()

    def _task_done(self, task: asyncio.Task):
        self._tasks.discard(task)
        if task.cancelled():
            return
        # Retrieved here, as a task can fail before wait() is called, or
        # without wait() being called at all.
        error = task.exception()
        if error is None:
            return
        self._errors.append(error)
        if len(self._errors) == 1:
            # As with trio and anyio, the first failure cancels the rest.
            for sibling in self._tasks:
                sibling.cancel()

    async def cancel(self):
        while self._tasks:
            task = self._tasks.pop()
            if not task.done():
                task.cancel()

    async def wait(self):
        """Waits for all tasks, including ones spawned while waiting. If a task
        fails, the others are cancelled, and once they've finished, the first
        exception is raised.
        """
        while self._tasks:
            await asyncio.wait(set(self._tasks))
        errors, self._errors = self._errors, []
        if errors:
            self._log_errors(errors[1:])
            raise errors[0]

    async def close(self):
        await self.cancel()
        # Such as when the group's body raised before wait() was reached.
        errors, self._errors = self._errors, []
        self._log_errors(errors)

    @staticmethod
    def _log_errors(errors):
        for error in errors:
            logger.error('Unhandled exception in a task group task.',
                         exc_info=error)
