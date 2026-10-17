import pytest

from serverwamp.routing import NoSuchRouteError, URIsRouter


async def a_handler():
    pass


async def b_handler():
    pass


async def exact_handler():
    pass


def build_router():
    router = URIsRouter()
    router.add_prefix_route('com.a.', a_handler)
    router.add_regex_route(r'^com\.b\.\d+$', b_handler)
    router.add_route('com.exact', exact_handler)
    return router


@pytest.mark.parametrize('uri, handler', (
    ('com.a.x', a_handler),
    ('com.b.1', b_handler),
    ('com.exact', exact_handler),
))
def test_resolve_matching_route(uri, handler):
    assert build_router().resolve(uri) is handler


@pytest.mark.parametrize('uri', ('com.b.x', 'com.zzz', 'com.exact.x'))
def test_resolve_unmatched_uri(uri):
    with pytest.raises(NoSuchRouteError):
        build_router().resolve(uri)
