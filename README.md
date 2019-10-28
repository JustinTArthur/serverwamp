# serverwamp
Components that add
[Web Application Messaging Protocol](https://wamp-proto.org/) features to
WebSocket servers. With serverwamp, a server can act as both a WAMP broker and
dealer. Currently supports ASGI servers using asyncio or Trio and aiohttp
servers.

## Usage
### Example
This service enables retrieval and removal of documents from a database via
two RPCs exposed to WAMP clients.
 
```python
from aiohttp import web
from serverwamp.adapters.aiohttp import WAMPApplication
from serverwamp.rpc import RPCRouteSet, RPCError

docs_api = RPCRouteSet()

@docs_api.route('docs.getDocument')
async def get_doc(document_id):
    record = await mydb.retrieve(document_id)
    return {'status': 'SUCCESS', 'document': record}

@docs_api.route('docs.deleteDocument')
async def delete_doc(document_id):
    succeeded = await mydb.delete(document_id)
    if succeeded:
        return {'status': 'SUCCESS'}
    else:
        raise RPCError('wamp.error.delete_failed', {'status': 'FAILURE'})


if __name__ == '__main__':
    wamp = WAMPApplication()
    wamp.add_rpc_routes(docs_api)

    app = web.Application()
    app.add_routes((web.get('/', wamp.handle),))
    web.run_app(app)
```
### Type Marshalling
RPC route handlers can supply type hints that are used to transform call
arguments passed in from the client.
```python
@rpc_api.route('slowlyCountToNumber')
async def slowly_count(count_to: int, interval: float, taunt: str = 'ah ah ah!'):
    for i in range(count_to):
        print(f'{i}, {taunt}')
        await asyncio.sleep(interval)
```
```python
from decimal import Decimal

@rpc_api.route('storeHighPrecisionTimestamp')
async def store_timestamp(timestamp: Decimal):
    pass
```
Without type hints, arguments are injected as they were parsed by the
deserializer (e.g. float for JSON Number).

### Built-in and Custom RPC Handler Arguments
If an RPC route contains arguments of certain names, these arguments are
automatically populated.

In this example for trio, a custom `nursery` argument is supplied for running
background tasks. The built-in argument `session` is requested so a background
task can later send an event to the session if it subscribed to the relevant
topic.

```python
import trio
from serverwamp.rpc import RPCRouteSet
from serverwamp.adapters.asgi_trio import WAMPApplication

async def long_running_job(session):
    await session.send_event('job_events', job_status='STARTED')
    await trio.sleep(3600)
    await session.send_event('job_events', job_status='COMPLETED')

rpc_api = RPCRouteSet()

@rpc_api.route('doJob')
async def do_job(self, nursery, session):
    nursery.start_soon(long_running_job(session))
    return 'Job scheduled.'

async def application(*args, **kwargs):
    async with trio.open_nursery() as rpc_nursery:
        wamp = WAMPApplication()
        wamp.set_default_rpc_arg('nursery', rpc_nursery)
        wamp.add_rpc_routes(rpc_api)

        return await wamp.asgi_application(*args, **kwargs)
```

## Compared to Traditional WAMP
Traditionally, WAMP clients connect to a WAMP router either to provide
functionality or to use functionality provided by other clients. This library
enables a server to respond to calls and subscriptions like a WAMP router
would, but serve them in a custom way instead of routing them to other clients.

You might do this to provide Python-based web services over a WebSocket using a
typical client and server model, while taking advantage of the structure the
WAMP protocol provides.

In summary, this is not a WAMP router, but you could use it to build one if you
wanted.

### This library is good if… 
* you like developing in micro-frameworks like Flask and
aiohttp, but want to branch into serving over WebSockets.
* you want a structure for communicating over WebSockets, but want more
request/response features than the socket.io protocol provides.
* you want to build a WAMP router.
### It's not useful if…
* you want to build a WAMP client
  * Consider [Autobahn|Python](https://autobahn.readthedocs.io/) instead.
* you want a WAMP router out of the box.
  * Consider [Crossbar.io](https://crossbar.io/) instead.

## Known Deficiencies
* Project is in the prototyping stages, so documentation isn't available on
low-level features yet.


## Development
Unit tests can be run with:

    pip install -e .
    pytest
