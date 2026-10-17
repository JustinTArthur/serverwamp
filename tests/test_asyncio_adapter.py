import asyncio
import gc

import pytest

from serverwamp.adapters.asyncio import AsyncioAsyncSupport

from memory_connection import run


class TaskError(Exception):
    pass


def test_task_failing_before_wait_is_retrieved_and_raised():
    loop_errors = []

    async def fail():
        raise TaskError()

    async def exercise():
        asyncio.get_event_loop().set_exception_handler(
            lambda loop, context: loop_errors.append(context)
        )
        with pytest.raises(ExceptionGroup) as exc_info:
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(fail)
                # The task fails while the group's body is still running.
                await asyncio.sleep(0.01)
        assert exc_info.group_contains(TaskError)
        gc.collect()
        await asyncio.sleep(0)

    run(exercise())
    assert not loop_errors


def test_failure_cancels_siblings():
    events = []

    async def fail():
        raise TaskError()

    async def sibling():
        try:
            await asyncio.sleep(1)
            events.append('sibling finished')
        except asyncio.CancelledError:
            events.append('sibling cancelled')
            raise

    async def exercise():
        with pytest.raises(ExceptionGroup) as exc_info:
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(fail)
                # Fails before the first failure's cancellations go out.
                await tasks.spawn(fail)
                await tasks.spawn(sibling)
        events.append('group exited')
        # The second failure is raised rather than lost.
        assert len(exc_info.value.exceptions) == 2

    run(exercise())
    # The group waits for the cancelled sibling before raising.
    assert events == ['sibling cancelled', 'group exited']


def test_task_spawned_after_failure_is_cancelled():
    events = []

    async def fail():
        raise TaskError()

    async def record():
        events.append('late task ran')

    async def spawn_late(tasks):
        try:
            await asyncio.sleep(1)
        finally:
            await tasks.spawn(record)

    async def exercise():
        with pytest.raises(ExceptionGroup):
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(spawn_late, tasks)
                await tasks.spawn(fail)

    run(exercise())
    assert not events


def test_task_spawned_after_group_exited_raises():
    async def record():
        pass

    async def exercise():
        async with AsyncioAsyncSupport.launch_task_group() as tasks:
            pass
        with pytest.raises(RuntimeError):
            await tasks.spawn(record)

    run(exercise())


def test_wait_includes_tasks_spawned_while_waiting():
    finished = []

    async def spawn_later(tasks):
        await asyncio.sleep(0.01)
        await tasks.spawn(finish)

    async def finish():
        await asyncio.sleep(0.01)
        finished.append('late task')

    async def exercise():
        async with AsyncioAsyncSupport.launch_task_group() as tasks:
            await tasks.spawn(spawn_later, tasks)

    run(exercise())
    assert finished == ['late task']


def test_body_error_cancels_tasks_and_is_raised():
    events = []

    async def wait_forever():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append('cancelled')
            raise

    async def exercise():
        with pytest.raises(ExceptionGroup) as exc_info:
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(wait_forever)
                await asyncio.sleep(0)
                raise KeyError()
        assert exc_info.group_contains(KeyError)

    run(exercise())
    assert events == ['cancelled']


def test_cancel_ends_tasks_without_failing_the_group():
    events = []

    async def wait_forever():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append('cancelled')
            raise

    async def exercise():
        async with AsyncioAsyncSupport.launch_task_group() as tasks:
            await tasks.spawn(wait_forever)
            await tasks.spawn(wait_forever)
            await asyncio.sleep(0)
            await tasks.cancel()
        events.append('group exited')

    run(exercise())
    assert events == ['cancelled', 'cancelled', 'group exited']
