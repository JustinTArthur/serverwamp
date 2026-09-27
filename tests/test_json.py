import pytest

from serverwamp.json import objects_from_json_batch


@pytest.mark.parametrize('batch, expected', (
    ('[1, "realm1", {}]\x1e', [[1, 'realm1', {}]]),
    (
        '[48, 1, {}, "a"]\x1e[48, 2, {}, "b"]\x1e',
        [[48, 1, {}, 'a'], [48, 2, {}, 'b']],
    ),
    ('[1,\n "realm1",\n {}]\x1e', [[1, 'realm1', {}]]),
    ('[1, "realm1", {}]', [[1, 'realm1', {}]]),
    ('', []),
))
def test_objects_from_json_batch(batch, expected):
    assert list(objects_from_json_batch(batch)) == expected
