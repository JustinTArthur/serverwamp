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
names are used when keyword arguments are supplied. Arguments serverwamp fills
in itself (``request``, ``session``, and default arguments set with
``set_default_arg()``) are skipped, so the caller's arguments only fill the
others.

A ``*args`` argument gets the caller's non-keyword arguments that no other
argument took, and a ``**kwargs`` argument gets the keyword arguments that
aren't named for another argument.

Type Marshalling
""""""""""""""""
RPC route handlers can supply type hints that are used to transform call
arguments passed in from the client.

.. code-block:: python

    @rpc_api.route('slowlyCountToNumber')
    async def slowly_count(count_to: int, interval: float, taunt: str = 'ah ah ah!'):
        for i in range(count_to):
            print(f'{i}, {taunt}')
            await asyncio.sleep(interval)

.. code-block:: python

    from decimal import Decimal

    @rpc_api.route('storeHighPrecisionTimestamp')
    async def store_timestamp(timestamp: Decimal):
        pass

Arguments that can't be converted to their type hint are answered with a
``wamp.error.invalid_argument`` error. Only class type hints are converted to,
so arguments hinted like ``int | None`` are passed as-is. Default values are
never converted.

Without type hints, arguments are injected as they were parsed by the
deserializer (e.g. float for JSON Number).

In addition to the arguments supplied by the caller, special pre-defined
argument names can be used in the function signature and serverwamp will fill
these in automatically. Out of the box, the ``request`` and ``session``
arguments are available.

.. code-block:: python

    async def local_file(filename, session):
        # filename is a regular WAMP RPC call argument, session is supplied
        # by serverwamp
        peer_address = session.connection.transport_info['peer_address']
        if peer_address != '127.0.0.1':
            return RPCErrorResult('wamp.error.not_authorized')

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

No return arguments:
""""""""""""""""""""

.. code-block:: python

    return None

Returning ``None``, or not returning a value at all, sends the caller a result
without arguments. To send ``None`` as the single return argument instead
(``[null]`` in JSON), return it in a tuple:

.. code-block:: python

    return None,

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
returning an ``RPCErrorResult`` with a WAMP error URI. Just like regular
results, errors can have arguments.

.. code-block:: python

    return serverwamp.RPCErrorResult(
        'wamp.error.invalid_argument',
        kwargs={
            'errorCode': 'BAD_INPUT',
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
A big benefit to having a persistent connection like a WebSocket is that events
can be pushed to clients without the client having to poll for new data and
without new connections needing to be established.

Given a ``Session`` object, events can be published to the client with
``Session.send_event()``. This could happen inside of an RPC procedure, or
in response to external event (from a message broker for example).

To keep track of what sessions have subscribed to a topic, you can register a
function to be called when a session subscribes to a topic. The function should
return an asynchronous iterator, and is most easily written as an asynchronous
generator function. The iterator's first part is the behavior when the
subscription is established and second part is behavior for when the
subscription is torn down or the session is closed. The function's arguments
are filled in by name: ``session`` gets the subscribing session, ``topic_uri``
gets the URI subscribed to, and others get default arguments set with
``set_default_arg()``.

If the function raises an exception before its ``yield``, the exception is
logged and the client's subscribe request is answered with a
``wamp.error.runtime_error`` error. Exceptions after the ``yield`` are logged,
and the subscription still ends.

.. code-block:: python

    events = serverwamp.TopicRouteSet()
    my_subscribers = set()


    @events.route('hourly_updates')
    async def subscribe_to_hourly_updates(session, my_subscribers):
        # On subscribe…
        my_subscribers.add(session)

        yield

        # On unsubscribe or session close…
        my_subscribers.remove(session)


    async def run_hourly_updates():
        while True:
            # A copy, as sessions can unsubscribe while events are sent.
            for session in list(my_subscribers):
                await session.send_event(
                    'hourly_updates',
                    args=(f'The hour is {datetime.now():%H}',)
                )
            await asyncio.sleep(60.0)

    app.add_topic_routes(events)
    app.set_default_arg('my_subscribers', my_subscribers)

    asyncio.create_task(run_hourly_updates())

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
``Application.asgi_application()`` produces an ASGI application that can be
run by an ASGI server or mounted in an ASGI framework. It serves WAMP
WebSockets using JSON or MsgPack serializations on the given paths, or on any
path if none are given. HTTP requests for those paths are answered with 426
Upgrade Required. HTTP requests for other paths are answered with 404, and
WebSockets for them are rejected. For servers that only support the older
ASGI 2 interface, use ``Application.legacy_asgi_application()`` instead.

.. _serverwamp-getting_started-authentication:

Authentication
--------------
Authentication can be required for new sessions. To require authentication,
supply one or more authenticator functions.

A realm can have any number of transport authenticators. If none of them
returns an identity, the session will be aborted as having failed
authentication.


Transport Authenticator
^^^^^^^^^^^^^^^^^^^^^^^
A transport authenticator can decide if a session is valid based on information
provided when the WAMP connection was established. It returns an identity of
any type if authentication succeeds or nothing if authentication fails.

Transport authenticators are configured by calling
``Realm.add_transport_authenticator`` or
``Application.add_transport_authenticator`` to add them to the default realm.

.. code-block:: python

    async def transport_authenticator(session):
        cookies = session.connection.transport_info['http_cookies']
        if cookies['myName'] == 'Jeff':
            identity = {'name': 'Jeff'}
            return identity

    app.add_transport_authenticator(transport_authenticator)

Some potential indicators that a transport authenticator could use to establish
a valid identity:

• ``session.auth_id`` (the WAMP authentication ID if provided, e.g.
  username)
• ``session.connection.transport_info['http_cookies']`` (mapping of cookie keys
  to value)
• ``session.connection.transport_info['peer_certificate']`` (if WAMP peer
  connected with SSL or TLS)
• ``session.connection.transport_info['peer_address']`` String of IP address or
  Unix path of the WAMP peer.

Ticket and Challenge-Response Authentication
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
serverwamp doesn't support WAMP ticket or challenge-response (WAMP-CRA)
authentication yet. ``set_ticket_authenticator`` and ``set_cra_handlers`` aren't
functional, so use transport authenticators instead.


Custom Authentication
^^^^^^^^^^^^^^^^^^^^^
To completely customize the authentication process, the core authentication
behavior can be replaced by a custom handler. See
:ref:`Custom Handlers/Authentication <custom_handlers-authentication>` for more
information.
