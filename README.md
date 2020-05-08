# serverwamp
Adds [Web Application Messaging Protocol](https://wamp-proto.org/) features to
WebSocket servers. _serverwamp_ makes it easy to both serve requests from
clients and push events to clients over a single connection. Currently supports
ASGI servers using asyncio or Trio and aiohttp servers.

[Documentation](https://serverwamp.readthedocs.io/)

### Usage Example
```python
from aiohttp import web
import serverwamp

docs_api = serverwamp.RPCRouteSet()

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
        return serverwamp.RPCErrorResult('wamp.error.delete_failed',
                                         kwargs={'status': 'FAILURE'})


if __name__ == '__main__':
    app = serverwamp.Application()
    app.add_rpc_routes(docs_api)

    http_app = web.Application()
    http_app.add_routes((web.get('/', app.aiohttp_websocket_handler()),))
    web.run_app(http_app)
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


## Development
Unit tests can be run with:

    pip install -e .
    pytest
