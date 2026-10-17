import pytest

from serverwamp.protocol import (
    WAMPGoodbyeRequest,
    WAMPHelloRequest,
    WAMPMsgParseError,
    WAMPMsgType,
    WAMPRPCRequest,
    WAMPSubscribeRequest,
    WAMPUnsubscribeRequest,
    wamp_request_from_msg,
)


def test_goodbye_fields():
    request = wamp_request_from_msg(
        [WAMPMsgType.GOODBYE, {'message': 'bye'}, 'wamp.close.close_realm']
    )
    assert request == WAMPGoodbyeRequest(
        reason_uri='wamp.close.close_realm',
        details={'message': 'bye'}
    )


@pytest.mark.parametrize('msg, expected', (
    ([1, 'realm', {}], WAMPHelloRequest('realm', {})),
    (
        (1, 'realm', {'authid': 'joe', 'authmethods': ('ticket',)}),
        WAMPHelloRequest('realm', {'authid': 'joe', 'authmethods': ('ticket',)})
    ),
    (
        [1, 'realm', {'authid': None, 'authmethods': None}],
        WAMPHelloRequest('realm', {'authid': None, 'authmethods': None})
    ),
    ([32, 1, {}, 'topic'], WAMPSubscribeRequest(1, 'topic', {})),
    ([34, 2, 3], WAMPUnsubscribeRequest(2, 3)),
    ([48, 4, {}, 'proc'], WAMPRPCRequest(4, {}, 'proc')),
    ([48, 4, {}, 'proc', [1]], WAMPRPCRequest(4, {}, 'proc', [1])),
    ([48, 4, {}, 'proc', [], {'a': 1}],
     WAMPRPCRequest(4, {}, 'proc', [], {'a': 1})),
))
def test_well_formed_requests(msg, expected):
    assert wamp_request_from_msg(msg) == expected


@pytest.mark.parametrize('msg', (
    # Not a message
    [],
    5,
    'hello',
    {'1': 'realm'},
    None,
    # Not a supported message type
    [1.0, 'realm', {}],
    [True, 'realm', {}],
    [[1], 'realm', {}],
    [999],
    # HELLO
    [1],
    [1, 'realm'],
    [1, ['realm'], {}],
    [1, 'realm', []],
    [1, 'realm', {'authid': 5}],
    [1, 'realm', {'authmethods': 'ticket'}],
    [1, 'realm', {'authmethods': [5]}],
    # SUBSCRIBE
    [32, 1, {}],
    [32, '1', {}, 'topic'],
    [32, 1, {}, ['topic']],
    # UNSUBSCRIBE
    [34, 1],
    [34, 1, 'subscription'],
    [34, None, 1],
    # CALL
    [48, 1, {}],
    [48, 1.0, {}, 'proc'],
    [48, 1, [], 'proc'],
    [48, 1, {}, 'proc', {}],
    [48, 1, {}, 'proc', [], []],
    # GOODBYE
    [6, {}],
    [6, 'wamp.close.close_realm', {}],
))
def test_malformed_requests(msg):
    with pytest.raises(WAMPMsgParseError):
        wamp_request_from_msg(msg)
