Advanced Usage
===============

Breaking an Application into Realms
-----------------------------------
Applications can give different WAMP sessions specialized authentication, call
handling, and events by breaking the application up into realms. serverwamp
applications have a default realm that all sessions are attached to if the
client requests a realm that hasn't been explicitly configured.

.. code-block:: python

    from myproject.apis import guests_realm, customers_realm, admins_realm

    guests_realm = serverwamp.Realm('guests')
    guests_realm.add_rpc_routes(registration_api)

    customers_realm = serverwamp.Realm('customers')
    customers_realm.add_transport_authenticator(customer_cookie_auth)
    customers_realm.add_rpc_routes(account_api)

    admins_realm = serverwamp.Realm('admins')
    admins_realm.set_ticket_authenticator(admin_token_auth)
    admins_realm.add_rpc_routes(admin_api)

    app.add_realm(guests_realm)
    app.add_realm(customers_realm)
    app.add_realm(admin_realm)

The default realm can be disabled during application setup:

.. code-block:: python

    app = serverwamp.Application(allow_default_realm=False)

With ``allow_default_realm`` set to ``False``, clients that specify a realm
that hasn't been configured in the application will have their connection
aborted with a ``wamp.error.no_such_realm`` error during session establishment.


Session Lifecycle
-----------------
When a connection starts speaking the WAMP protocol to serverwamp, a session
is established between the client and server. Once the session is authenticated,
the client may call procedures on the server and the server may publish events
to the client. The session can be closed by the client or server or is
implicitly closed if the underlying connection (e.g.WebSocket) is closed before
that.

Session Open and Close
^^^^^^^^^^^^^^^^^^^^^^

Custom behavior can be run when a session is opened or closed by adding session
state handlers to the application. Session state handlers are written as
asynchronous iterators whose first iteration is run when a session is started
and the next when the session is closed.

.. code-block:: python

    async def count_session(session, app_metrics):
        # `session` is auto-populated with the current serverwamp session
        # `app_metrics` is a custom application-wide default argument.

        # This part is called when the session is authenticated…
        app_metrics['activeSessions'] += 1

        yield

        # This part is called when the session is closed…
        app_metrics['activeSessions'] -= 1

    app.set_default_arg('app_metrics', {'activeSessions': 0})

Just like RPC and subscription route handlers, the session state handler can
receive default arguments from the application realm.

Session Data
^^^^^^^^^^^^

At any point in time during the session's lifecycle, custom data that is
important to your app can be set or retrieved on the session object. The
current session is available to RPC route handlers, topic route subscription
handlers, and session state handlers by adding an argument named ``session`` to
the function signature.

.. code-block:: python

    @rpc_api.route('set_my_name')
    async def set_my_name(name, session):
        # `session` is auto-populated with the current serverwamp session
        session['name'] = name


Asynchronous Function Support
-----------------------------
serverwamp uses asynchronous functions so code can run while other code is
waiting for something like a timer or a network response.

In Python, async functions are run using a library that can start, pause, and
resume code based on operating system mechanics. There are a few of these
libraries available. By default, serverwamp uses *asyncio* from the Python
standard library set; however, an alternative asynchronous handling library
can be used to take advantage of different connection adapters or asynchronous
handling features in custom application code. It is completely up to the
serverwamp integrator.

Asynchronous handling support other than the default must be specified when
the app is created:

.. code-block:: python
    :caption: Example using Trio

    from serverwamp.adapters.trio import TrioAsyncSupport
    app = serverwamp.Application(async_support=TrioAsyncSupport)

A few asynchronous support libraries are provided out of the box:

• ``serverwamp.adapters.anyio.AnyioAsyncSupport`` for
  :doc:`AnyIO <anyio:index>`
• ``serverwamp.adapters.asyncio.AsyncioAsyncSupport`` for
  :doc:`asyncio <library/asyncio>` (the default)
• ``serverwamp.adapters.trio.TrioAsyncSupport`` for
  :doc:`Trio <trio:index>`

Customizing Core WAMP Operations
--------------------------------

.. _custom_handlers-authentication:

Authentication
^^^^^^^^^^^^^^
In most cases, supplying one or more
:ref:`regular authentication handlers <serverwamp-getting_started-authentication>`
is sufficient for most authentication needs. If not, the core authentication
behavior can be overridden.

Following WAMP standards, an authentication handler will receive a brand new
session and do one of two things:

``await session.mark_authenticated(identity)`` where ``identity`` can be
anything.

or

``await session.abort('wamp.error.authentication_failed')`` with optional
``message=`` keyword argument.



RPC Calls
^^^^^^^^^
If you don't want to use the built-in call router, a custom handler can be
supplied to handle procedure calls however you want. Routes registered with
``Application.add_routes`` or ``Realm.add_routes`` will not be used in
this case.

A basic RPC handler either returns an :py:meth:`~serverwamp.rpc.RPCResult` or
an :py:meth:`~serverwamp.rpc.RPCError`.

.. code-block:: python

    from serverwamp.rpc import RPCRequest, RPCResult, RPCErrorResult

    async def rpc_handler(rpc_request: RPCRequest) -> Any:
        if rpc_request.uri = 'add_stuff':
            if not all(isinstance(arg, (int, float)) for arg in rpc_request.args):
                return RPCErrorResult(args=('Numbers only!',))
            total = sum(rpc_request.args)
            return RPCResult(args=(total,))
        else:
            return RPCErrorResult('myapp.custom_error')

    my_realm.set_rpc_handler(rpc_handler)

Progressive results are also supported by supplying a handler that returns
and async iterator that produces any number of
:py:meth:`~serverwamp.rpc.RPCProgressReport`\ s and a final
:py:meth:`~serverwamp.rpc.RPCResult` or an :py:meth:`~serverwamp.rpc.RPCError`.

An async generator is the easiest way to do this:

.. code-block:: python

    from serverwamp.rpc import (RPCProgressReport, RPCRequest, RPCResult,
                                RPCErrorResult)

    async def rpc_handler(rpc_request: RPCRequest) -> Any:
        if rpc_request.uri != 'add_stuff':
            yield RPCErrorResult('myapp.custom_error')

        total = 0
        for num in rpc_request.args:
            if not isinstance(num, (float,int)):
                yield RPCErrorResult(args=('Numbers only!',))
                return
            total += num
            yield RPCProgressReport(args=(f'Added {num}'))

        yield RPCResult(args=(total,))

