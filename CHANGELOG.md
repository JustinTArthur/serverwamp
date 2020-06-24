# serverwamp Changelog
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
