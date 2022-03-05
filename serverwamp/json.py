"""Helper functions for dealing with WAMP JSON serialization/deserialization"""
import importlib.util
import logging
import re
from base64 import b64decode, b64encode
from collections.abc import ByteString
from typing import Any

JSON_LIBS_PREFERENCE = (
    'rapidjson',
    'orjson',
    'json'
)
JSON_PACKED_BYTES_PREFIX = '\x00'
JSON_BATCH_SPLITTER = '\x1e'

logger = logging.getLogger(__name__)

match_jsons_in_batch = re.compile(f'(.+?)(?:{JSON_BATCH_SPLITTER}|$)').finditer

for module in JSON_LIBS_PREFERENCE:
    if importlib.util.find_spec(module):
        json_lib = importlib.import_module(module)
        JSON_LIBRARY = module
        break
else:
    raise ImportError('No suitable JSON parsing module found.')


if JSON_LIBRARY == 'json':
    logger.warning('Using standard json library for JSON serialization. '
                   'Binary value deserialization is not possible with this '
                   'library.')

    class _WAMPJSONEncoder(json_lib.JSONEncoder):
        def default(self, obj: Any):
            if isinstance(obj, ByteString):
                return (
                    JSON_PACKED_BYTES_PREFIX
                    + b64encode(obj).decode('ascii')
                )
            raise TypeError(f'{obj} is not JSON serializable')

    deserialize = json_lib.loads
    serialize = _WAMPJSONEncoder().encode

elif JSON_LIBRARY == 'rapidjson':
    class _WAMPJSONDecoder(json_lib.Decoder):
        def string(self, s: str):
            if s and s[0] == JSON_PACKED_BYTES_PREFIX:
                return b64decode(s[1:])
            return s

    class _WAMPJSONEncoder(json_lib.Encoder):
        def default(self, obj: Any):
            if isinstance(obj, ByteString):
                return (
                    JSON_PACKED_BYTES_PREFIX
                    + b64encode(obj).decode('ascii')
                )
            raise TypeError(f'{obj} is not JSON serializable')

    deserialize = _WAMPJSONDecoder()
    serialize = _WAMPJSONEncoder()

elif JSON_LIBRARY == 'orjson':
    logger.warning('Found orjson library for JSON serialization. Binary value '
                   'deserialization is not possible with this library.')

    def _obj_fallback(obj: Any) -> Any:
        if isinstance(obj, ByteString):
            return (
                JSON_PACKED_BYTES_PREFIX
                + b64encode(obj).decode('ascii')
            )
        raise TypeError(f'{obj} is not JSON serializable')

    def serialize(obj: Any, *args, **kwargs):
        json_bytes = json_lib.dumps(obj, *args, default=_obj_fallback,
                                    **kwargs)
        # WAMP transports use character strings
        return json_bytes.decode('utf-8')

    deserialize = json_lib.loads


def jsons_from_batch(batch: str):
    for match in match_jsons_in_batch(batch):
        yield match[1]
