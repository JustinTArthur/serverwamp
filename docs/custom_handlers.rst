Custom Core WAMP Operation Handlers
===================================

.. _custom_handlers-authentication:

Authentication
--------------
In most cases, supplying one or more regular authentication handlers is
sufficient for most authentication needs. If not, the core authentication
behavior can be overridden.

Following WAMP standards, an authentication handler will receive a brand new
session and do one of two things:

``await session.mark_authenticated(identity)`` where ``identity`` can be
anything.

or

``await session.abort('wamp.error.authentication_failed')`` with optional
``message=`` keyword argument.



RPC Calls
---------
If you don't want to use the built-in call router, a custom handler can be
supplied to handle procedure calls however you want. Routes registered with
:code:`Application.add_routes` or :code:`Realm.add_routes` will not be used in
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

Progressive results are also supported by supplying a handler that returns
and async iterator that produces any number of
:py:meth:`~serverwamp.rpc.RPCProgressReport`\ s and a final
:py:meth:`~serverwamp.rpc.RPCResult` or an :py:meth:`~serverwamp.rpc.RPCError`.

A async generator is the easiest way to do this:

.. code-block:: python

    from serverwamp.rpc import RPCProgressReport, RPCRequest, RPCResult, RPCErrorResult

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

