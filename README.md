# aiohttp-server-wamp
This library serves as an adapter to aiohttp, enabling an aiohttp server
to serve JSON WAMP features over WebSockets. With aiohttp-server-wamp, an
aiohttp server can act as both a WAMP broker and WAMP dealer.

## Compared to Traditional WAMP
Traditionally, WAMP clients connect to a WAMP router either to provide
functionality or to use functionality provided by other clients. This library
enables a developer to respond to calls and subscriptions like a WAMP router
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
### It's not as useful if…
* you want to build a WAMP client
  * Consider [Autobahn|Python](https://autobahn.readthedocs.io/) instead.
* you want a WAMP router out of the box.
  * Consider [Crossbar.io](https://crossbar.io/) instead.

## Example WAMP Microservice
```python
from aiohttp import web
from aiohttp_server_wamp.aiohttp import WAMPApplication
from aiohttp_server_wamp.rpc import RPCRouteTableDef, RPCErrorResponse

rpc_routes = RPCRouteTableDef()

@rpc_routes.route('myapp:getDoc')
async def get_document(document_id):
    record = await mydb.retrieve(document_id)
    return {'status': 'SUCCESS', 'document': record}
    
@rpc_routes.route('myapp:delDoc')
async def delete_document(document_id):
    succeeded = await mydb.delete(document_id)
    if succeeded:
        return {'status': 'SUCCESS'}
    else:
        return RPCErrorResponse(status='FAILURE')
    

if __name__ == '__main__':
    wamp = WAMPApplication()
    wamp.add_rpc_routes(rpc_routes)

    app = web.Application()
    app.add_routes((web.get('/', wamp.handle),))
    web.run_app(app)
```

## Known Deficiencies
* Project is in the prototyping stages, so documentation isn't available on
low-level features yet.
* The out-of-the-box RPC handler does not provide the URI, session ID or call ID
to the function that the call is routed to. This may be addressed in a later
version with arg inspection/injection or async context vars.