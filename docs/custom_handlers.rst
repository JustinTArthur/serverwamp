Custom WAMP Operation Handlers
==============================

Authentication
--------------
    .. function:: a_function(session):
        cookies = session.connection.transport_info['http_cookies']
        if cookies['myName'] == 'Jeff':
            await session.mark_authenticated()
        else:
            raise serverwamp.AuthenticationError()
