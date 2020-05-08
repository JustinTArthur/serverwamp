"""
Defines base classes for how async support classes should look, mostly
to ease serverwamp development or to ease integration in type-checked projects.
"""
import typing
from abc import ABC, abstractmethod
from typing import Awaitable, Callable


if hasattr(typing, 'AsyncContextManager'):
    TaskGroupManager = typing.AsyncContextManager['AsyncTaskGroup']
else:
    from serverwamp.context import AbstractAsyncContextManager
    TaskGroupManager = AbstractAsyncContextManager


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
    async def shield(cls,
         callback: Callable[..., Awaitable],
         *callback_args,
         **callback_kwargs
    ):
        pass
