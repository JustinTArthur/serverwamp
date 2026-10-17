"""Serves WAMP from an ASGI app on Trio, such as with:

    hypercorn --worker-class trio trio_asgi_rpc_and_pubsub:application

Calling doJob starts a job that reports its progress to the caller's
job_events subscription. Jobs run in a nursery that lasts as long as the
server, so they finish even if the caller disconnects, and they're cancelled
when the server shuts down.
"""
import trio

import serverwamp
from serverwamp.adapters.trio import TrioAsyncSupport

JOB_SECONDS = 60

rpc_api = serverwamp.RPCRouteSet()
topics = serverwamp.TopicRouteSet()


async def report_job_status(session, job_status):
    try:
        await session.send_event('job_events',
                                 kwargs={'job_status': job_status})
    except serverwamp.ConnectionClosed:
        # The caller left, but the job carries on.
        pass


async def long_running_job(session):
    await report_job_status(session, 'STARTED')
    await trio.sleep(JOB_SECONDS)
    await report_job_status(session, 'COMPLETED')


@rpc_api.route('doJob')
async def do_job(job_nursery, session):
    job_nursery.start_soon(long_running_job, session)
    return 'Job scheduled.'


@topics.route('job_events')
async def job_events():
    # Events go straight to subscribed sessions, so there's nothing to set up
    # or tear down.
    yield


wamp = serverwamp.Application(async_support=TrioAsyncSupport)
wamp.add_rpc_routes(rpc_api)
wamp.add_topic_routes(topics)
wamp_application = wamp.asgi_application()


async def lifespan(receive, send):
    async with trio.open_nursery() as job_nursery:
        wamp.set_default_arg('job_nursery', job_nursery)
        await receive()  # lifespan.startup
        await send({'type': 'lifespan.startup.complete'})
        await receive()  # lifespan.shutdown
        job_nursery.cancel_scope.cancel()
    await send({'type': 'lifespan.shutdown.complete'})


async def application(scope, receive, send):
    if scope['type'] == 'lifespan':
        await lifespan(receive, send)
    else:
        await wamp_application(scope, receive, send)
