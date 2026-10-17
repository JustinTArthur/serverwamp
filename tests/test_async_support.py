"""Exercises each AsyncSupport on the event loops it supports."""
import anyio
import pytest

import serverwamp
from serverwamp.adapters.anyio import AnyioAsyncSupport
from serverwamp.adapters.asyncio import AsyncioAsyncSupport
from serverwamp.adapters.trio import TrioAsyncSupport
from serverwamp.protocol import WAMPMsgType

from stream_connection import TIMEOUT, StreamConnection

pytestmark = pytest.mark.parametrize('async_support, backend', (
    (AsyncioAsyncSupport, 'asyncio'),
    (AnyioAsyncSupport, 'asyncio'),
    (AnyioAsyncSupport, 'trio'),
    (TrioAsyncSupport, 'trio'),
))


class TaskError(Exception):
    pass


def test_spawned_tasks_finish_before_group_exits(async_support, backend):
    finished = []

    async def finish(name, suffix=''):
        await anyio.sleep(0.01)
        finished.append(name + suffix)

    async def exercise():
        async with async_support.launch_task_group() as tasks:
            await tasks.spawn(finish, 'positional')
            await tasks.spawn(finish, 'keyword', suffix='!')

    anyio.run(exercise, backend=backend)
    assert sorted(finished) == ['keyword!', 'positional']


def test_failure_cancels_siblings_and_raises_group(async_support, backend):
    events = []

    async def fail():
        raise TaskError()

    async def sibling():
        try:
            await anyio.sleep(1)
            events.append('sibling finished')
        except anyio.get_cancelled_exc_class():
            events.append('sibling cancelled')
            raise

    async def exercise():
        with pytest.raises(ExceptionGroup) as exc_info:
            async with async_support.launch_task_group() as tasks:
                await tasks.spawn(sibling)
                await tasks.spawn(fail)
        assert exc_info.group_contains(TaskError)
        events.append('group exited')

    anyio.run(exercise, backend=backend)
    assert events == ['sibling cancelled', 'group exited']


def test_cancel_ends_tasks_without_failing_group(async_support, backend):
    events = []

    async def wait_forever():
        try:
            await anyio.sleep(3600)
        except anyio.get_cancelled_exc_class():
            events.append('cancelled')
            raise

    async def exercise():
        with anyio.fail_after(TIMEOUT):
            async with async_support.launch_task_group() as tasks:
                await tasks.spawn(wait_forever)
                await anyio.sleep(0.01)
                await tasks.cancel()
        events.append('group exited')

    anyio.run(exercise, backend=backend)
    assert events == ['cancelled', 'group exited']


def test_shield_runs_callback_through_cancellation(async_support, backend):
    events = []

    async def clean_up(label, suffix=''):
        await anyio.sleep(0.01)
        events.append(label + suffix)
        return 'result'

    async def shielded():
        try:
            await anyio.sleep(3600)
        finally:
            result = await async_support.shield(clean_up, 'cleaned',
                                                suffix=' up')
            events.append(result)

    async def exercise():
        async with async_support.launch_task_group() as tasks:
            await tasks.spawn(shielded)
            await anyio.sleep(0.01)
            await tasks.cancel()

    anyio.run(exercise, backend=backend)
    assert events == ['cleaned up', 'result']


def test_session_handles_rpc_call(async_support, backend):
    async def procedure():
        return 'called'

    routes = serverwamp.RPCRouteSet()
    routes.route('procedure')(procedure)
    app = serverwamp.Application(async_support=async_support)
    app.add_rpc_routes(routes)

    async def exercise():
        connection = StreamConnection()
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(app.handle_connection, connection)
            await connection.deliver([WAMPMsgType.HELLO, 'realm', {}])
            assert (await connection.receive())[0] == WAMPMsgType.WELCOME
            await connection.deliver([WAMPMsgType.CALL, 1, {}, 'procedure'])
            assert list(await connection.receive()) == [
                WAMPMsgType.CALL_RESULT, 1, {}, ('called',)
            ]
            await connection.close()

    anyio.run(exercise, backend=backend)
