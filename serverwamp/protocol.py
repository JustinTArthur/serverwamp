import json
import logging
import secrets
from base64 import b64encode
from collections import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum, unique
from random import randint
from typing import Iterable, Mapping, Optional

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
    details: Mapping

    @classmethod
    def from_msg_data(cls, msg_data: Sequence):
        try:
            request = cls(realm_uri=msg_data[0], details=msg_data[1])
        except KeyError:
            raise WAMPMsgParseError('Poorly formed hello')
        return request


@dataclass(frozen=True)
class WAMPRequest:
    request_id: int


@dataclass(frozen=True)
class WAMPSubscribeRequest(WAMPRequest):
    topic: str
    options: Mapping

    @classmethod
    def from_msg_data(cls, msg_data: Sequence):
        try:
            request = cls(
                request_id=msg_data[0],
                options=msg_data[1],
                topic=msg_data[2]
            )
        except KeyError:
            raise WAMPMsgParseError('Poorly formed subscribe')
        return request


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

    @classmethod
    def from_msg_data(cls, msg_data: Sequence):
        try:
            request = cls(
                request_id=msg_data[0],
                subscription=msg_data[1]
            )
        except KeyError:
            raise WAMPMsgParseError('Poorly formed unsubscribe')
        return request


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
    def from_msg_data(cls, msg_data: Sequence):
        try:
            request_id = msg_data[0]
            uri = msg_data[2]
            if len(msg_data) > 3:
                args = msg_data[3]
            else:
                args = ()
            if len(msg_data) > 4:
                kwargs = msg_data[4]
            else:
                kwargs = {}
        except KeyError:
            raise WAMPMsgParseError('Poorly formed RPC call')

        if not isinstance(request_id, int) or not isinstance(uri, str):
            raise WAMPMsgParseError('Poorly formed RPC call')

        request = cls(
            request_id,
            uri=uri,
            options=msg_data[1],
            args=args,
            kwargs=kwargs
        )
        return request


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
    reason_uri: str
    details: Mapping = field(default_factory=dict)

    @classmethod
    def from_msg_data(cls, msg_data: Sequence):
        try:
            request = cls(
                request_id=msg_data[0],
                details=msg_data[1],
                reason_uri=msg_data[2] if len(msg_data) > 2 else None
            )
        except KeyError:
            raise WAMPMsgParseError('Poorly formed goodbye')
        return request


def call_result_response_msg(
    request: WAMPRPCRequest,
    args: Optional[Sequence] = None,
    kwargs=None,
    progress=False
) -> Sequence:
    details = {}
    if progress:
        details['progress'] = True
    if kwargs:
        return (WAMPMsgType.CALL_RESULT, request.request_id, details, args or (),
                kwargs)
    if args:
        return WAMPMsgType.CALL_RESULT, request.request_id, details, args
    return WAMPMsgType.CALL_RESULT, request.request_id, details


def call_error_response_msg(
    request: WAMPRPCRequest,
    error_uri: str,
    args: Optional[Sequence] = None,
    kwargs: Optional[Mapping] = None
):
    if kwargs:
        return (WAMPMsgType.ERROR, WAMPMsgType.CALL, request.request_id, {},
                error_uri, args or (), kwargs)
    if args:
        return (WAMPMsgType.ERROR, WAMPMsgType.CALL, request.request_id, {},
                error_uri, args)
    return (WAMPMsgType.ERROR, WAMPMsgType.CALL, request.request_id, {},
            error_uri)


def subscribed_response_msg(
    request: WAMPSubscribeRequest,
    subscription_id
) -> Iterable:
    return WAMPMsgType.SUBSCRIBED, request.request_id, subscription_id


def unsubscribe_error_response_msg(
    request: WAMPUnsubscribeRequest,
    error_uri
):
    return (WAMPMsgType.ERROR, WAMPMsgType.UNSUBSCRIBE, request.request_id, {},
            error_uri)


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


def scram_nonce() -> str:
    """A nonce (number used once) presented as a base64-encoded sequence of
    random octets of sufficient length to make a replay attack unfeasible.

    Per WAMP specification, a length of 16 octets (128 bits) is recommended for
    each of the client and server-generated nonces.

    Can be used for both WAMP-CRA and WAMP-SCRAM authentication
    """
    raw_nonce = secrets.token_bytes(16)
    return b64encode(raw_nonce).encode('ascii')


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


def event_msg(
    subscription_id: int,
    publication_id: int,
    args: Optional[Sequence] = (),
    kwargs: Optional[Mapping] = None,
    trust_level: Optional[int] = None,
    specific_topic: Optional[str] = None
):
    details = {}
    if trust_level is not None:
        details['trustlevel'] = trust_level
    if specific_topic:
        details['topic'] = specific_topic

    if kwargs:
        return (WAMPMsgType.EVENT, subscription_id, publication_id, details,
                args or (), kwargs)
    if args:
        return (WAMPMsgType.EVENT, subscription_id, publication_id, details,
                args)

    return WAMPMsgType.EVENT, subscription_id, publication_id, details


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
    WAMPMsgType.HELLO: WAMPHelloRequest.from_msg_data,
    WAMPMsgType.CALL: WAMPRPCRequest.from_msg_data,
    WAMPMsgType.SUBSCRIBE: WAMPSubscribeRequest.from_msg_data,
    WAMPMsgType.UNSUBSCRIBE: WAMPUnsubscribeRequest.from_msg_data,
    WAMPMsgType.GOODBYE: WAMPGoodbyeRequest.from_msg_data
}


def wamp_request_from_msg(
    msg: Sequence
) -> WAMPRequest:
    msg_type, *msg_data = msg
    try:
        parse_msg = request_parser_for_msg_type[msg_type]
    except KeyError:
        raise WAMPMsgParseError('Unsupported request')
    request = parse_msg(msg_data)
    return request


class WAMPMsgParseError(Exception):
    """An issue with the types, order, length, or contents of what was presumed
    to be WAMP message data
    """
    pass
