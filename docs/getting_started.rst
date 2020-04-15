Getting Started
===============

Application Setup
-----------------
An Application object holds the configuration of your WAMP app and provides
adapters to start serving the application to connections.

Breaking an Application into Realms
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Applications can optionally give different WAMP sessions specialized
authentication, call handling, and events by breaking the application up into
realms. serverwamp applications have a default realm that all sessions are
attached to if the client requests a realm that hasn't been explicitly
configured

.. code-block:: python

    guests_realm = serverwamp.Realm('guests')
    guests_realm.add_routes(registration_api)

    customers_realm = serverwamp.Realm('customers')
    customers_realm.add_transport_authenticator(customer_cookie_auth)
    customers_realm.add_routes(account_api)

    admins_realm = serverwamp.Realm('admins')
    admins_realm.set_ticket_authenticator(admin_token_auth)
    admins_realm.add_routes(admin_api)

    app.add_realm(guests_realm)
    app.add_realm(customers_realm)
    app.add_realm(admin_realm)


The default realm can be disabled during application setup:

.. code-block:: python

    app = serverwamp.Application(allow_default_realm=False)

With ``allow_default_realm`` set to ``False``, clients that specify a realm
that hasn't been configured in the application will have their connection
aborted with a ``wamp.error.no_such_realm`` error during session establishment.

Asynchronous Function Behavior
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
serverwamp uses asynchronous functions so code can run while other code is
waiting for something like a timer or a network response.

In Python, async functions are run using libraries that start, pause, and
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

Connection Adapters
-------------------

aiohttp WebSockets
^^^^^^^^^^^^^^^^^^^^^^^^^^

ASGI Server WebSockets
^^^^^^^^^^^^^^^^^^^^^^


