"""
Defines base classes for how async support classes should look, mostly
to ease serverwamp development or to ease integration in type-checked projects.
"""
from abc import ABC, abstractmethod
from typing import AsyncContextManager, Awaitable, Callable


class AsyncTaskGroup(ABC):
    @abstractmethod
    async def spawn(
        self,
        callback: Callable[..., Awaitable],
        *callback_args,
        **callback_kwargs
    ) -> None:
        pass

    @abstractmethod
    async def cancel(self) -> None:
        """
        Cancels any pending/running/outstanding tasks.
        """


class AsyncSupport(ABC):
    @abstractmethod
    @classmethod
    def launch_task_group(self) -> AsyncContextManager[AsyncTaskGroup]:
        pass
