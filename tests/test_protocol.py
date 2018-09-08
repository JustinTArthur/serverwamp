import json

from aiohttp_server_wamp import protocol


def test_publish_event():
    sent_msgs = []

    class CollectingTransport:
        @staticmethod
        def schedule_msg(msg):
            sent_msgs.append(msg)

    proto = protocol.WAMPProtocol(transport=CollectingTransport(),)

    event1 = protocol.WAMPEvent()
    proto.publish_event(87624, event1)

    event2 = protocol.WAMPEvent(args=['a1', 'a2', 3, 4, 5])
    proto.publish_event(87624, event2)

    event3 = protocol.WAMPEvent(kwargs={'k1': 'v1', 1: 2})
    proto.publish_event(87624, event3)

    event4 = protocol.WAMPEvent(args=(7, 8, 9), kwargs={'k1': 'v1', 1: 2})
    proto.publish_event(87624, event4)

    event5 = protocol.WAMPEvent(publication=87059872)
    proto.publish_event(87624, event5)

    assert(len(sent_msgs) == 5)
    for msg in sent_msgs:
        assert msg.startswith('[36,')

    msg1 = json.loads(sent_msgs[0])
    assert msg1[1] == 87624
    assert isinstance(msg1[2], int)
    assert 1 <= msg1[2] <= 9007199254740992
    assert msg1[3] == {}

    msg2 = json.loads(sent_msgs[1])
    assert msg2[1] == 87624
    assert isinstance(msg2[2], int)
    assert 1 <= msg2[2] <= 9007199254740992
    assert msg2[3] == {}
    assert msg2[4] == ['a1', 'a2', 3, 4, 5]

    msg3 = json.loads(sent_msgs[2])
    assert msg3[1] == 87624
    assert isinstance(msg3[2], int)
    assert 1 <= msg3[2] <= 9007199254740992
    assert msg3[3] == {}
    assert msg3[4] == []
    # Key names must be strings in JSON so kwargs keys will also be strings.
    assert msg3[5] == {'k1': 'v1', '1': 2}

    msg4 = json.loads(sent_msgs[3])
    assert msg4[1] == 87624
    assert isinstance(msg4[2], int)
    assert 1 <= msg4[2] <= 9007199254740992
    assert msg4[3] == {}
    assert msg4[4] == [7, 8, 9]
    assert msg4[5] == {'k1': 'v1', '1': 2}

    msg5 = json.loads(sent_msgs[4])
    assert msg5[1] == 87624
    assert msg5[2] == 87059872
    assert msg5[3] == {}
    assert len(msg5) == 4
