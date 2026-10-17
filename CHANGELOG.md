# serverwamp Changelog
## Unreleased
* Require Python 3.11 or newer. `serverwamp.context`, a backport of
`contextlib.asynccontextmanager` for older Pythons, is removed.
* Build the asyncio support on `asyncio.TaskGroup`. As with Trio and AnyIO,
task group failures, including unhandled errors while handling a connection,
are raised as an `ExceptionGroup` instead of the first error alone, and a
failing task interrupts the code that started the group.
* Support current AnyIO and Trio releases, now requiring AnyIO 4 or newer and
Trio 0.25 or newer. They can be installed with serverwamp's `anyio` and `trio`
extras.
* Abort sessions for protocol errors with `wamp.error.protocol_violation`,
per WAMP spec, instead of `wamp.error.protocol_error`.
* Handle these client mistakes instead of failing in the connection handler:
  * WebSocket messages that aren't valid JSON or MessagePack, WAMP messages
    that are too short or have fields of the wrong type, and HELLO after the
    session is established abort the session with a protocol violation.
    Message types must be integers, so `1.0` and `true` are no longer accepted
    as HELLO.
  * UNSUBSCRIBE for a subscription the session doesn't have is answered with
    `wamp.error.no_such_subscription`.
  * SUBSCRIBE for a topic without a route is answered with
    `wamp.error.invalid_uri`.
  * HELLO with a null `authmethods` that no transport authenticator identifies
    is aborted with `wamp.error.authentication_failed`.
* Fix GOODBYE details and reason being read from the wrong fields.
`WAMPGoodbyeRequest` no longer has a `request_id`.
* Give GOODBYE messages a reason instead of none. Replies to a client's GOODBYE
and `WAMPSession.close()` without a reason use `wamp.close.goodbye_and_out`,
and `Application.close_sessions()` uses `wamp.close.system_shutdown`.
* End sessions once GOODBYE has been exchanged, instead of when the client
disconnects. Subscription and session state teardown run then, and the
connection handler returns.
  * After the session sends GOODBYE, messages from the client other than its
    GOODBYE in reply are ignored, per WAMP spec.
  * Sending for a session that has ended raises `serverwamp.ConnectionClosed`,
    including from call handlers still running and from `send_event()`.
* Fix prefix and regex routes handling URIs they don't match. A call or
subscription for a URI without an exact route went to the first prefix or regex
route added.
  * Applications relying on this should add a catch-all route such as
    `prefix_route('')` after their other prefix and regex routes.
* Answer SUBSCRIBE for a topic the session is already subscribed to with the
existing subscription, without running the subscription handler again.
* Fix RPCs that finish after their client disconnected logging errors,
cancelling the session's other calls, and keeping the session in memory.
  * Sends to a disconnected client raise `serverwamp.ConnectionClosed`, a
    `ConnectionError`, instead of the transport's own exception.
  * `WAMPSession.close()` and `abort()` succeed when the client already left.
  * Unhandled exceptions from a session's tasks are logged. With Trio or AnyIO,
    they no longer end the session.
* Run progressive RPC handlers' `finally` blocks as soon as their call is
handled, instead of at garbage collection.
* Wait for tasks started with `WAMPSession.spawn_task()` while a session ends,
instead of cancelling them.
* Fix sessions never being cleaned up with Trio. Teardown after `yield` in
subscription and session state handlers now runs, and ended sessions are no
longer kept in memory.
* Fix ASGI apps failing on anything other than a WebSocket. HTTP requests are
answered with 426 Upgrade Required without an error, and lifespan startup and
shutdown are acknowledged, so an app from `asgi_application()` can be served
directly.
* Rename `serverwamp.adapters.asgi.ASGIWebSocketConection` to
`ASGIWebSocketConnection`.
* Reject WebSocket connections that offer none of the supported WAMP
subprotocols, with 400 Bad Request with aiohttp and 403 Forbidden from ASGI
servers. aiohttp upgraded them and then failed in the request handler, and ASGI
accepted them with `wamp.2.msgpack.batched`, which the client hadn't offered.
* Fix RPC handlers given to `set_rpc_handler()` failing on every call unless
their parameter was named `rpc_request`.

## 1.2.0
* Fix the default realm never being used. Sessions requesting a realm that
wasn't added with `add_realm` now join the default realm as documented instead
of being aborted with `wamp.error.no_such_realm`.
  * To reject realms that weren't added, use
    `Application(allow_default_realm=False)`. Configuring the default realm
    through the application (e.g. `add_rpc_routes`) then raises a
    `RuntimeError` instead of an `AttributeError`.
* Fix single RPC return values (e.g. `return 'hello'`) being sent as the
result arguments themselves instead of as a single-element argument list.
  * Returning `None` still sends a result without arguments. Return `None,` to
    send `None` as the single argument.
* Support Python 3.14 and 3.15, and allow msgpack 1.x releases newer than 1.0.
* Package with pyproject.toml and hatchling.
* Fix aiohttp logging request handler errors when the server ended a
connection.
* Fix `wamp.2.json.batched` sessions being aborted with a protocol error, and
batched JSON messages containing line breaks being dropped.
* Fix ASGI `wamp.2.json` sessions failing on the first message sent to the
client.
* Fix `Application(synchronize_requests=True)` failing every session on its
first request after the welcome.
* Fix messages batched in the same WebSocket message as a client's HELLO being
dropped.
* Declare public names in `__all__` so strict type checkers accept imports such
as `serverwamp.Application`.

## 1.1.2
* Fix standard library json support.

## 1.1.1
* Support session close goodbye message.

## 1.0.7
* Fix using deprecated collections.Sequence.
* WAMP-compliant msgpack batch processing
  * Fixes Autobahn|Python out-of-box compatibility.
* Allow unauthenticated sessions if no authenticators configured.
  * `session.identity` is `None` in this case.

## 1.0.6
* Server now responds with error when unsubscribing from non-subscribed topic.
* Temporarily synchronize subscribe/unsubscribe messages.
  * Synchronization will be made configurable by request type in a future version.
* Fix for exception raised in trying to process protocol messages from a
canceled connection.

## 1.0.5
* Fix error in SCRAM nonce generation
* Fix lack of response to clients' unsubscribe requests
* Fix for exception raised in trying to process protocol messages from a
canceled connection. 

## 1.0.4
* aiohttp sessions now cancellable by server shutdown
* Session cleanup operations specifically shielded from cancellation
* Added Application.close_sessions method (undocumented)

## 1.0.3
* Fix for plain topic routes raising exception during registration.
[Issue #4](JustinTArthur/serverwamp#4)
* Exceptions in user-supplied RPC code no longer crash the app, but instead
return a wamp.error.runtime_error to the caller like Crossbar.io's toolchain.

## 1.0.2
* Add "http_headers_raw" transport_info item for aiohttp and ASGI connections. 

## 1.0.1
* Fix stopasynciteration exception on session close with outstanding subscriptions.

## 1.0.0
Brand new API with…
* Support for multiple realms w/ separate handlers
* Context-manager-friendly subscription handlers
* Session state handlers.
* Routes configuration for topics similar to RPC.
* Slightly more structured concurrency on the asyncio side.
* Transport authenticators, ticket authenticators, and CRA auth.

Released 2020-05-07 alongside new documentation.

## 0.2.3
Transport auth, RPC and subscriptions now working.
