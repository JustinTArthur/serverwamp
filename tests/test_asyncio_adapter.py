import asyncio
import gc
import logging

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
        with pytest.raises(TaskError):
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(fail)
                # The task fails while the group's body is still running.
                await asyncio.sleep(0.01)
        gc.collect()
        await asyncio.sleep(0)

    run(exercise())
    assert not loop_errors


def test_failure_cancels_siblings(caplog):
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
        with pytest.raises(TaskError):
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(fail)
                # Fails before the first failure's cancellations go out.
                await tasks.spawn(fail)
                await tasks.spawn(sibling)
        events.append('group exited')

    with caplog.at_level(logging.ERROR):
        run(exercise())
    # The group waits for the cancelled sibling before raising.
    assert events == ['sibling cancelled', 'group exited']
    # The second failure is logged rather than lost.
    assert [record.exc_info[0] for record in caplog.records] == [TaskError]


def test_task_spawned_after_failure_is_cancelled():
    events = []

    async def fail():
        raise TaskError()

    async def record():
        events.append('late task ran')

    async def exercise():
        with pytest.raises(TaskError):
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(fail)
                await asyncio.sleep(0.01)
                await tasks.spawn(record)

    run(exercise())
    assert not events


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


def test_errors_logged_when_wait_not_reached(caplog):
    async def fail():
        raise TaskError()

    async def exercise():
        with pytest.raises(KeyError):
            async with AsyncioAsyncSupport.launch_task_group() as tasks:
                await tasks.spawn(fail)
                await asyncio.sleep(0.01)
                raise KeyError()

    with caplog.at_level(logging.ERROR):
        run(exercise())
    assert [record.exc_info[0] for record in caplog.records] == [TaskError]
