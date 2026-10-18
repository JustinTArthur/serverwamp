from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from re import Pattern
from typing import Any

from serverwamp.routing import URIsRouter
from serverwamp.session import WAMPSession

SubscriptionHandler = Callable[[str, WAMPSession], AsyncIterator[Any]]


class SubscribeError(Exception):
    """Raised by a subscription handler before its yield to answer the
    SUBSCRIBE with an ERROR of the given URI, such as
    wamp.error.not_authorized.
    """
    def __init__(self, error_uri: str):
        super().__init__(error_uri)
        self.error_uri = error_uri


class TopicRouteSet(Sequence):
    """Table of subscription handlers for WAMP topics."""
    def __init__(self):
        self._items = []

    def __repr__(self):
        return f'<TopicRouteSet count={len(self._items)}>'

    def __getitem__(self, index):
        return self._items[index]

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __contains__(self, item):
        return item in self._items

    def route(self, uri, **kwargs):
        def inner(handler):
            self._items.append(TopicRouteDef(uri, handler, kwargs))
            return handler

        return inner

    def prefix_route(self, uri_prefix, **kwargs):
        def inner(handler):
            self._items.append(TopicPrefixRouteDef(uri_prefix, handler, kwargs))
            return handler

        return inner

    def regex_route(self, uri_pattern, **kwargs):
        def inner(handler):
            self._items.append(TopicRegexRouteDef(uri_pattern, handler, kwargs))
            return handler

        return inner


@dataclass(frozen=True)
class TopicRouteDef:
    uri: str
    handler: Callable[..., Awaitable]
    kwargs: Mapping

    def register(self, router):
        router.add_route(self.uri, self.handler, **self.kwargs)


@dataclass(frozen=True)
class TopicPrefixRouteDef:
    uri_prefix: str
    handler: Callable[..., Awaitable]
    kwargs: Mapping

    def register(self, router):
        router.add_prefix_route(self.uri_prefix, self.handler, **self.kwargs)


@dataclass(frozen=True)
class TopicRegexRouteDef:
    uri_pattern: str | Pattern[str]
    handler: Callable[..., Awaitable]
    kwargs: Mapping

    def register(self, router):
        router.add_regex_route(self.uri_pattern, self.handler, **self.kwargs)


class TopicsRouter(URIsRouter):
    async def handle_subscription(
        self,
        topic_uri: str,
        session: WAMPSession
    ) -> AsyncIterator[None]:
        procedure = self.resolve(topic_uri)

        handler_args, handler_kwargs = session.realm._args_for_realm_level_handler(
            procedure, topic_uri=topic_uri, session=session
        )
        handler_invocation = procedure(*handler_args, **handler_kwargs)
        if not isinstance(handler_invocation, AsyncIterator):
            """TODO: raise error"""
            return
        await handler_invocation.__anext__()
        yield
        try:
            await handler_invocation.__anext__()
        except StopAsyncIteration:
            pass
        else:
            """TODO: Raise more than one yield error."""
