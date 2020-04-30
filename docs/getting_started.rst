Getting Started
===============

Application Setup
-----------------
An Application object holds the configuration of your WAMP app and provides
adapters to start serving the application to connections.

.. code-block:: python

    import serverwamp

    app = serverwamp.Application()

The configuration of an application can include procedures the client can call,
handlers for client event subscriptions, and ways to authenticate and identify
a client when it connects.

Remote Procedure Calls
----------------------
A simple Python async function can serve requests from clients that expect a
response. These kind of requests are called remote procedure calls or RPCs. The
data that serves as the input for the request and the data included in the
response are called arguments.

Python functions used to serve these requests are assigned a "route", a URI
used by clients to identify the procedure they want to call.

.. code-block:: python

    # First create a route set:
    math_api = serverwamp.RPCRouteSet()

    # Next add a procedure and register it with a route
    @math_api.route('math.add')
    async def add_numbers(number1, number2):
        """Adds two numbers together"""
        total = number1 + number2

        # This procedure has a single return argument:
        return total

    # Add registered routes to the application serving clients:
    app.add_routes(math_api)


Function Call Arguments
^^^^^^^^^^^^^^^^^^^^^^^
The order and name of arguments in the function signature are important.
The order is used when non-keyword arguments are supplied by the caller and the
names are used when keyword arguments are supplied.

In addition to the arguments supplied by the caller, special pre-defined
argument names can be used in the function signature and serverwamp will fill
these in automatically. Out of the box, the ``request`` and ``session``
arguments are available.

.. code-block:: python

    async def local_file(filename, session):
        # filename is a regular WAMP RPC call argument, session is supplied
        # by serverwamp
        if session.connection.transport_info['peer_address'] != '127.0.0.1':
            return RPCErrorResult(args=('Not authorized',))

        with open(filename, 'r') as file:
            return file.read()

Function Return Arguments
^^^^^^^^^^^^^^^^^^^^^^^^^

Single return argument:
"""""""""""""""""""""""

.. code-block:: python

    return 42

Any serializable non-mapping, non-list, and non-tuple can be returned and it
will be used as the single return argument to the caller.

Positional return arguments:
""""""""""""""""""""""""""""

.. code-block:: python

    return 'Peanut Butter', 'Jelly', 'Bread'

A tuple or list of items of any serializable types can be returned and they
will be positional arguments in the result.

Keyword return arguments:
"""""""""""""""""""""""""

.. code-block:: python

    return {'gregorianYear': 2020, '生肖': '鼠'}

If a mapping type is returned, the keys and values construct keyword arguments
returned to the caller.

Custom return arguments:
""""""""""""""""""""""""

.. code-block:: python

    return serverwamp.RPCResult(
        args=('Rock & Roll', 'Blues', 'Jazz'),
        kwargs={
            'playlistLength': 6432,
            'playlistSubscribers': 51
        }
    )

Any combination of serializable arguments and keyword arguments can be returned
by constructing an ``RPCResult``.

Error responses:
""""""""""""""""
You can respond to the caller to let them know an error has occurred by
returning an ``RPCErrorResult``. Just like regular results, errors can have
arguments.

.. code-block:: python

    return serverwamp.RPCErrorResult(
        kwargs={
            'errorCode': 'BAD_INPUT'
            'errorMessage': 'You should have supplied a number instead of a string.'
        }
    )


Progressive responses:
""""""""""""""""""""""
An RPC handler function can push progress reports down to clients waiting for a
result by fashioning your RPC handler as an asynchronous iterator that produces
any number of RPCProgressReports followed by a final ``RPCResult`` or
``RPCErrorResult``. The easiest way to create an RPC handler like this is by
making an asynchronous generator function.

.. code-block:: python

    async def countdown_to_liftoff():
        for time_left in 3, 2, 1:
            yield serverwamp.RPCProgressReport(
                kwargs={'timeLeft': time_left}
            )
            await asyncio.sleep(1)

        yield serverwamp.RPCResult(kwargs={'liftoffStatus': 'SUCCESS'})

WAMP clients that don't support progressive results will only see the end
result or error.

Sending Events to Clients
-------------------------
Given a ``Session`` object, events can be published to the client with
``Session.send_event()``. This could happen inside of an RPC procedure, or
in response to external event (from a message broker for example). To keep
track of what sessions have subscribed to a topic, you can register methods to
be called when a session subscribes to or unsubscribes from a topic.

.. code-block:: python

    class UpdatesWorker:
        def __init__(self):
            self._to_update = set()

        async def handle_subscribe(topic, session):
            if topic == 'hourly_updates':
                self._to_update.add(session)

        async def handle_unsubscribe(topic, session):
            if topic == 'hourly_updates':
                self._to_update.remove(session)

        async def run():
            while True:
                for session in self._to_update():
                    session.send_event(
                        args=(f'The hour is {datetime.now():%H}',)
                    )
                await asyncio.sleep(60.0)

    updates_worker = UpdatesWorker()
    app.add_subscribe_handler(updates_worker.handle_subscribe)
    app.add_unsubscribe_handler(updates_worker.handle_unsubscribe)

Serving Connections
-------------------
The WAMP protocol is designed to be served over a streaming network transport
layer like HTTP WebSockets or TCP. serverwamp serves WAMP peers using the
networking features of other libraries. It also makes it easy to serve WAMP
connections in the same HTTP server as other routes such as RESTful HTTP.

aiohttp WebSockets
^^^^^^^^^^^^^^^^^^
aiohttp is a popular async HTTP server (and client) library built on top of
Python's asyncio. ``Application.aiohttp_websocket_handler()`` produces an
aiohttp web request handler that can be assigned an HTTP route. The route will
then serve WAMP WebSockets using JSON or MsgPack serializations. The WAMP app
can be served alongside other HTTP or even other WebSocket routes.

ASGI Server WebSockets
^^^^^^^^^^^^^^^^^^^^^^
``Application.asgi_application()`` produces an aiohttp web request
handler that can be assigned an HTTP route. The route will then serve WAMP
WebSockets using JSON or MsgPack serializations.

.. _serverwamp-getting_started-authentication:

Authentication
--------------
Authentication can be required for new sessions. To require authentication,
supply one or more authenticator functions.

A realm can have any number of transport authenticators, but only one
challenge-based authenticator like ticket or CRA. If no transport authenticator
has marked the session as authenticated, then severwamp will proceed with any
supplied challenge-based authenticator. If no authenticators return
an identity, the session will be aborted as having failed authentication.


Transport Authenticator
^^^^^^^^^^^^^^^^^^^^^^^
A transport authenticator can decide if a session is valid based on information
provided when the WAMP connection was established. It returns an identity of
any type if authentication succeeds or nothing if authentication fails.

Transport authenticators are configured by calling
``Realm.add_transport_authenticator`` or
``Application.add_transport_authenticator`` to add them to the default realm.

.. code-block:: python

    async def transport_authenticator(session) -> Any:
        cookies = session.connection.transport_info['http_cookies']
        if cookies['myName'] == 'Jeff':
            identity = {'name': 'Jeff'}
            return identity

    app.add_transport_authenticator(transport_authenticator)

Some potential indicators that a transport authenticator could use to establish
a valid identity:

• ``session.auth_id`` (the WAMP authentication ID if provided, e.g.
  username)
• ``session.connection.transport_info['http_cookies']`` (mapping of cookie keys to
  value)
• ``session.connection.transport_info['peer_certificate']`` (if WAMP peer connected
  with SSL or TLS)
• ``session.connection.transport_info['peer_address']`` String of IP address or Unix
  path of the WAMP peer.

Ticket Authenticator
^^^^^^^^^^^^^^^^^^^^
Ticket authenticators are configured by calling
:code:`Realm.set_ticket_authenticator` or
:code:`Application.set_ticket_authenticator` to set the ticket authenticator
for the default realm. It returns an identity of any type if authentication
succeeds or nothing if authentication fails. Only one ticket authenticator is
allowed per-realm.

.. code-block:: python

    async def ticket_authenticator(session, ticket) -> Any:
        if ticket in auth_db:
            return identity

    app.set_ticket_authenticator(ticket_authenticator)

Challenge-Response Authenticator
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
In order to make CRA challenges, two callables are required, a requirement
provider and an identity provider. If the peer successfully proves they have
the same secret from the requirement provider, the session's identity will be
retrieved from the identity provider. Only one set of CRA handlers are allowed
per realm.

.. code-block:: python

    import serverwamp

    async def cra_requirement_provider(session) -> Any:
        secret = await my_company_auth_db.retrieve_secret(session.auth_id)
        req = serverwamp.CRAAuthRequirement(
            auth_role='RegularUser',
            auth_provider='my_company_auth_db'
            secret=secret
        )
        return req

    async def cra_identity_provider(session):
        """Called only when CRA auth is successful."""
        user = await my_company_users_db.retrieve_user(session.auth_id)
        return user

    app.set_cra_handlers(cra_requirement_provider, cra_identity_provider)


Custom Authentication
^^^^^^^^^^^^^^^^^^^^^
To completely customize the authentication process, the core authentication
behavior can be replaced by a custom handler. See
:ref:`Custom Handlers/Authentication <custom_handlers-authentication>` for more
information.
