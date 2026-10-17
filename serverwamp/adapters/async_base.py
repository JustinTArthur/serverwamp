"""
Defines base classes for how async support classes should look, mostly
to ease serverwamp development or to ease integration in type-checked projects.
"""
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

TaskGroupManager = AbstractAsyncContextManager['AsyncTaskGroup']


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
    @classmethod
    @abstractmethod
    def launch_task_group(cls) -> TaskGroupManager:
        pass

    @classmethod
    @abstractmethod
    async def shield(
        cls,
        callback: Callable[..., Awaitable],
        *callback_args,
        **callback_kwargs
    ):
        pass
