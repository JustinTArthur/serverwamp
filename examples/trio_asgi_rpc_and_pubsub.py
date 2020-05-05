import trio
import serverwamp
from serverwamp.adapters.trio import TrioAsyncSupport


async def long_running_job(session):
    await session.send_event('job_events', job_status='STARTED')
    await trio.sleep(3600)
    await session.send_event('job_events', job_status='COMPLETED')

rpc_api = serverwamp.RPCRouteSet()


@rpc_api.route('doJob')
async def do_job(self, nursery, session):
    nursery.start_soon(long_running_job(session))
    return 'Job scheduled.'


async def application(*args, **kwargs):
    async with trio.open_nursery() as rpc_nursery:
        wamp = serverwamp.Application(async_support=TrioAsyncSupport)
        wamp.set_default_arg('nursery', rpc_nursery)
        wamp.add_rpc_routes(rpc_api)

        return await wamp.asgi_application(*args, **kwargs)
