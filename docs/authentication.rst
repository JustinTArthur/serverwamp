Authentication
==============
Authentication can be required for new sessions. To require authentication,
supply one or more authenticator functions.

A realm can have any number of transport authenticators, but only one
challenge-based authenticator like ticket or CRA. If no transport authenticator
has marked the session as authenticated, then severwamp will proceed with any
supplied challenge-based authenticator. If no supplied authenticators marked
the session as authenticated or raised a :code:`serverwamp.AuthenticationError`
exception then the session will be aborted as having failed authentication.


Transport Authenticator
-----------------------
A transport authenticator can decide if a session is valid based on information
provided when the WAMP connection was established. It returns an identity of
any type if authentication succeeds or nothing if authentication fails.

Transport authenticators are configured by calling
:code:`Realm.add_transport_authenticator` or
:code:`Application.add_transport_authenticator` to add them to the default
realm.

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
• ``session.transport_info['http_cookies']`` (mapping of cookie keys to
  value)
• ``session.transport_info['peer_certificate']`` (if WAMP peer connected
  with SSL or TLS)
• ``session.transport_info['peer_address']`` String of IP address or Unix
  path of the WAMP peer.

Ticket Authenticator
--------------------
Ticket authenticators are configured by calling
:code:`Realm.set_ticket_authenticator` or
:code:`Application.set_ticket_authenticator` to set the ticket authenticator
for the default realm. It returns an identity of any type if authentication
succeeds or nothing if authentication fails. Only one ticket authenticator
is allowed per-realm.

    .. code-block:: python

        async def ticket_authenticator(session, ticket) -> Any:
            if ticket in auth_db:
                return identity

        app.set_ticket_authenticator(ticket_authenticator)

Challenge-Response Authenticator
--------------------------------
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
---------------------
To completely customize the authentication process, the core authentication
behavior can be replaced by a custom handler. See
:ref:`Custom Handlers/Authentication <custom_handlers-authentication>` for more
information.
