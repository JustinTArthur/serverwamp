serverwamp Documentation
========================
Adds `Web Application Messaging Protocol <https://wamp-proto.org/>`_ features
to WebSocket servers. *serverwamp* makes it easy to both serve requests from
clients and push events to clients over a single connection. It currently
supports ASGI servers or aiohttp.

Example service that allows WebSocket clients to retrieve or remove documents
from a database:

.. code-block:: python

    import asyncio

    from aiohttp import web
    import serverwamp

    docs_api = serverwamp.RPCRouteSet()
    docs_events = serverwamp.TopicRouteSet()

    @docs_api.route('docs.getDoc')
    async def get_doc(document_id):
        record = await my_db.retrieve(document_id)
        return {'status': 'SUCCESS', 'doc': record}

    @docs_api.route('docs.deleteDoc')
    async def delete_doc(document_id):
        succeeded = await my_db.delete(document_id)
        if succeeded:
            return {'status': 'SUCCESS'}

        return serverwamp.RPCErrorResult(
            'wamp.error.delete_failed',
            kwargs={'status': 'FAILURE'}
        )

    @docs_events.route('docs.changes')
    async def subscribe_to_doc_changes(session, changes_subscribers):
        changes_subscribers.add(session)
        session.send_event(args=('Thanks for subscribing!',))
        yield
        changes_subscribers.remove(session)


    async def server_context(app):

        async def watch_for_docs_changes():
            async for event in my_db.watch_changes():
                for session in app['changes_subscribers']:
                    await session.send_event(f'Document changed: {event}')

        watcher = asyncio.create_task(watch_for_docs_changes())

        try:
            yield
        finally:
            watcher.cancel()


    if __name__ == '__main__':
        changes_subscribers = set()

        app = serverwamp.Application()
        app.add_rpc_routes(docs_api)
        app.add_topic_routes(docs_events)
        app.set_default_arg('changes_subscribers', changes_subscribers)

        http_app = web.Application()
        http_app['changes_subscribers'] = changes_subscribers
        http_app.add_routes((
            web.get('/', app.aiohttp_websocket_handler()),
        ))
        http_app.cleanup_ctx.append(server_context)

        web.run_app(http_app)

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   getting_started
   advanced_usage
   compared_to_traditional_wamp



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
