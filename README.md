# serverwamp
Components that add
[Web Application Messaging Protocol](https://wamp-proto.org/) features to
WebSocket servers. With serverwamp, a server can act as both a WAMP broker and
dealer. Currently supports ASGI servers using asyncio or Trio and aiohttp
servers.

## Example WAMP Microservice
This service enables retrieval and removal of documents from a database via
two RPCs exposed to WAMP clients.
 
```python
from aiohttp import web
from serverwamp.adapters.aiohttp import WAMPApplication
from serverwamp.rpc import RPCRouteTableDef, RPCError

rpc = RPCRouteTableDef()

@rpc.route('docs.getDocument')
async def get_document(document_id):
    record = await mydb.retrieve(document_id)
    return {'status': 'SUCCESS', 'document': record}

@rpc.route('docs.deleteDocument')
async def delete_document(document_id):
    succeeded = await mydb.delete(document_id)
    if succeeded:
        return {'status': 'SUCCESS'}
    else:
        raise RPCError('wamp.error.delete_failed', {'status': 'FAILURE'})


if __name__ == '__main__':
    wamp = WAMPApplication()
    wamp.add_rpc_routes(rpc)

    app = web.Application()
    app.add_routes((web.get('/', wamp.handle),))
    web.run_app(app)
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
