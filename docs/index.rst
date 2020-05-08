serverwamp Documentation
========================
Adds `Web Application Messaging Protocol <https://wamp-proto.org/>`_ features
to WebSocket servers. *serverwamp* makes it easy to both serve requests from
clients and push events to clients over the same connection. It currently
supports ASGI servers or aiohttp.

Example service that allows WebSocket clients to retrieve or remove documents
from a database:

.. code-block:: python

    from aiohttp import web
    import serverwamp

    docs_api = serverwamp.RPCRouteSet()

    @docs_api.route('docs.getDoc')
    async def get_doc(document_id):
        record = await mydb.retrieve(document_id)
        return {'status': 'SUCCESS', 'document': record}

    @docs_api.route('docs.deleteDoc')
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
        http_app.add_routes((
            web.get('/', app.aiohttp_websocket_handler()),
        ))
        web.run_app(http_app)

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   getting_started
   advanced_usage



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
