import json
import logging

from collections import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum, unique
from random import randint
from typing import Iterable, Mapping, Optional

from serverwamp.session import WAMPSession

logger = logging.getLogger(__name__)


@unique
class WAMPMsgType(IntEnum):
    HELLO = 1
    WELCOME = 2
    ABORT = 3
    CHALLENGE = 4

    GOODBYE = 6
    ERROR = 8

    CALL = 48
    CALL_RESULT = 50
    INVOCATION = 68

    SUBSCRIBE = 32
    SUBSCRIBED = 33

    UNSUBSCRIBE = 34
    UNSUBSCRIBED = 35

    PUBLISH = 16
    PUBLISHED = 17
    EVENT = 36


def generate_global_id():
    """Returns an integer that can be used for globally scoped identifiers in
    WAMP communications. Per the WAMP spec, these are random."""
    return randint(1, 9007199254740992)


class AuthenticationFailure(Exception):
    def __init__(self, reason: str = None):
        self.reason = reason


@dataclass(frozen=True)
class WAMPHelloRequest:
    realm_uri: str
    details: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPRequest:
    session: WAMPSession
    request_id: int


@dataclass(frozen=True)
class WAMPSubscribeRequest(WAMPRequest):
    options: Mapping
    uri: str


@dataclass(frozen=True)
class WAMPSubscribeResponse(WAMPRequest):
    request: WAMPSubscribeRequest
    subscription: int


@dataclass(frozen=True)
class WAMPSubscribeErrorResponse:
    request: WAMPSubscribeRequest
    uri: str
    details: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPUnsubscribeRequest(WAMPRequest):
    subscription: int


@dataclass(frozen=True)
class WAMPUnsubscribeErrorResponse:
    request: WAMPUnsubscribeRequest
    uri: str
    details: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPEvent:
    publication: int = field(default_factory=generate_global_id)
    details: Mapping = field(default_factory=dict)
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPRPCRequest(WAMPRequest):
    options: Mapping
    uri: str
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)

    @classmethod
    def from_msg(cls, msg: Sequence):
        request_id = msg[0]
        uri = msg[2]
        if len(msg) > 3:
            args = msg[3]
        else:
            args = ()
        if len(msg) > 4:
            kwargs = msg[4]
        else:
            kwargs = {}

        if not isinstance(request_id, int) or not isinstance(uri, str):
            raise WAMPMsgParseError('Poorly formed RPC call')

        try:
            request = WAMPRPCRequest(
                request_id,
                uri=uri,
                options={},
                args=args,
                kwargs=kwargs
            )
        except Exception as e:
            result_msg = (
                WAMPMsgType.ERROR,
                WAMPMsgType.CALL,
                request_id,
                {},
                'wamp.error.exception_during_rpc_call',
                str(e)
            )
        return cls()



@dataclass(frozen=True)
class WAMPRPCResponse:
    request: WAMPRPCRequest
    details: Mapping = field(default_factory=dict)
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPRPCErrorResponse:
    request: WAMPRPCRequest
    uri: str
    details: Mapping = field(default_factory=dict)
    args: Sequence = ()
    kwargs: Mapping = field(default_factory=dict)


@dataclass(frozen=True)
class WAMPGoodbyeRequest(WAMPRequest):
    request: WAMPRequest
    uri: str
    details: Mapping = field(default_factory=dict)


def call_result_response_msg(request: WAMPRPCRequest, args=(), kwargs=None) -> Iterable:
    return (
        WAMPMsgType.CALL_RESULT,
        request.request_id,
        {},
        args,
        kwargs
    )


def subscribed_response_msg(
    request: WAMPSubscribeRequest,
    subscription_id
) -> Iterable:
    return WAMPMsgType.SUBSCRIBED, request.request_id, subscription_id


def unsubscribed_response_msg(request: WAMPUnsubscribeRequest) -> Iterable:
    return WAMPMsgType.UNSUBSCRIBED, request.request_id


def unimplemented_response_msg(request: WAMPRequest) -> Iterable:
    return (
        WAMPMsgType.ERROR,
        request.request_id,
        {},
        'wamp.error.not_implemented'
    )


def cra_challenge_msg(challenge_string: str) -> Iterable:
    return WAMPMsgType.CHALLENGE, 'wampcra', {'challenge': challenge_string}


def ticket_challenge_msg() -> Iterable:
    return WAMPMsgType.CHALLENGE, 'ticket', {}


def welcome_msg(session_id, agent_name=None) -> Iterable:
    details = {
        'roles': {
            'broker': {},
            'dealer': {}
        }
    }
    if agent_name:
        details['agent'] = agent_name
    return (
        WAMPMsgType.WELCOME,
        session_id,
        details
    )


def goodbye_msg(reason_uri='wamp.close.goodbye_and_out'):
    return WAMPMsgType.GOODBYE, {}, reason_uri


def abort_msg(reason_uri, message):
    details = {}
    if message:
        details['message'] = message
    return WAMPMsgType.ABORT, details, reason_uri


def cra_challenge_string(
    session_id: int,
    auth_id: str,
    auth_role: str,
    auth_provider: str,
    nonce: str,
    auth_time: Optional[datetime] = None
) -> str:
    """Returns a string used in a WAMP CRA challenge using a mix of identifying
    and random data."""
    if auth_time is None:
        auth_time = datetime.now(timezone.utc)
    challenge_string = json.dumps(
        {
            'authid': auth_id,
            'authprovider': auth_provider,
            'authrole': auth_role,
            'nonce': nonce,
            'session_id': session_id,
            'timestamp': auth_time.isoformat()
        },
        sort_keys=True
    )
    return challenge_string


request_parser_for_msg_type = {
    WAMPMsgType.HELLO: WAMPHelloRequest.from_msg,
    WAMPMsgType.CALL: WAMPRPCRequest.from_msg,
    WAMPMsgType.SUBSCRIBE: WAMPSubscribeRequest.from_msg,
    WAMPMsgType.UNSUBSCRIBE: WAMPUnsubscribeRequest.from_msg
}


def wamp_request_from_msg(
    msg: Sequence,
    session: Optional[WAMPSession]
) -> WAMPRequest:
    msg_type, *msg_data = msg[0]
    if msg_type not in msg_data:
        raise WAMPMsgParseError('Unsupported request')
    request = request_parser_for_msg_type[msg_type](msg_data)
    return request


class WAMPMsgParseError(Exception):
    pass
