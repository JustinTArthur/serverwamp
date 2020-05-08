Compared to Traditional WAMP
============================
In the traditional WAMP model, WAMP peers connect to a WAMP router either to
provide functionality or to use functionality provided by other peers. This can
be very useful in the *Internet of Things* where you have devices coming online
and offline with each device bringing along a unique set of services.

This library enables a server to respond to calls and subscriptions like a WAMP
router would, but serve them itself instead of routing to other clients.

You might do this to provide Python-based web services over a WebSocket using a
typical client and server model, while taking advantage of the structure the
WAMP protocol provides.


This library is good if…
------------------------
• you like developing in micro-frameworks like Flask and aiohttp, but want to
  branch into serving over WebSockets.
• you want a structure for communicating over WebSockets, but want more
  request/response features than socket.io or MQTT over Websockets provides.
• you want to build a WAMP router.

It's not useful if…
-------------------
• you want to build a WAMP client or peer

  • Consider `Autobahn|Python <https://autobahn.readthedocs.io/>`_ instead.

• you want a WAMP router out of the box.

  • Consider `Crossbar.io <https://crossbar.io/>`_ instead.
