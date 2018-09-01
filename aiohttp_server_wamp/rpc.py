from collections.abc import Sequence

import attr


class WampNoSuchProcedureError(Exception):
    pass


class Router:
    def __init__(self):
        self.dispatch_table = {}

    def add_route(self, uri, handler):
        self.dispatch_table[uri] = handler

    def resolve(self, uri):
        try:
            handler = self.dispatch_table[uri]
        except KeyError:
            raise WampNoSuchProcedureError('Procedure %s does not exist.', uri)
        return handler

    def add_routes(self, routes):
        """Append routes to route table.

        Parameter should be an iterable of RPCRouteDef objects.
        """
        for route_obj in routes:
            route_obj.register(self)


@attr.s(frozen=True, repr=False, slots=True)
class RPCRouteDef:
    uri = attr.ib(type=str)
    handler = attr.ib()
    kwargs = attr.ib()

    def __repr__(self):
        info = []
        for name, value in sorted(self.kwargs.items()):
            info.append(f', {name}={value!r}')
        return (f'<RPCRouteDef {self.uri} -> {self.handler.__name__!r}'
                f'{"".join(info)}>')

    def register(self, router):
        router.add_route(self.uri, self.handler, **self.kwargs)


def route(uri, handler, **kwargs):
    return RPCRouteDef(uri, handler, kwargs)


class RPCRouteTableDef(Sequence):
    """WAMP RPC route definition table. Similar to aiohttp.web.RouteTableDev"""
    def __init__(self):
        self._items = []

    def __repr__(self):
        return f'<RPCRouteTableDef count={len(self._items)}>'

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
            self._items.append(RPCRouteDef(uri, handler, kwargs))
            return handler
        return inner
