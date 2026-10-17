from serverwamp.protocol import (WAMPGoodbyeRequest, WAMPMsgType,
                                 wamp_request_from_msg)


def test_goodbye_fields():
    request = wamp_request_from_msg(
        [WAMPMsgType.GOODBYE, {'message': 'bye'}, 'wamp.close.close_realm']
    )
    assert request == WAMPGoodbyeRequest(
        reason_uri='wamp.close.close_realm',
        details={'message': 'bye'}
    )
