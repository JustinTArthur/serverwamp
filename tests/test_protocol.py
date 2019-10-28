import json
import socket

from serverwamp import protocol


def test_publish_event():
    sent_msgs = []

    class CollectingTransport(protocol.Transport):
        @staticmethod
        def get_extra_info(info_name):
            if info_name == 'peername':
                return '127.0.0.1', 80
            elif info_name == 'socket':
                return socket.socket()

        def send_msg_soon(self, msg):
            sent_msgs.append(msg)

        async def send_msg(self, msg: str) -> None:
            sent_msgs.append(msg)

        async def close(self):
            pass

    proto = protocol.WAMPProtocol(transport=CollectingTransport())

    proto.do_event(87624)
    proto.do_event(87624, args=['a1', 'a2', 3, 4, 5])
    proto.do_event(87624, kwargs={'k1': 'v1', 1: 2})
    proto.do_event(87624, args=(7, 8, 9), kwargs={'k1': 'v1', 1: 2})
    proto.do_event(87624, publication_id=87059872)

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
