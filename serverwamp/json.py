"""Helper functions for dealing with WAMP JSON serialization/deserialization"""
import importlib.util
import warnings
from base64 import b64decode, b64encode
from collections.abc import ByteString
from typing import Any

JSON_LIBS_PREFERENCE = (
    'rapidjson',
    'orjson',
    'json'
)
SUBCLASSABLE_LIBS = {
    'rapidjson',
    'json'
}
JSON_PACKED_BYTES_PREFIX = '\x00'

for module in JSON_LIBS_PREFERENCE:
    if importlib.util.find_spec(module):
        json_lib = importlib.import_module(module)
        JSON_LIBRARY = module
        break
else:
    raise ImportError('No suitable JSON parsing module found.')


if JSON_LIBRARY in SUBCLASSABLE_LIBS:
    class WAMPJSONDecoder(json_lib.Decoder):
        def string(self, s: str):
            if s and s[0] == JSON_PACKED_BYTES_PREFIX:
                return b64decode(s[1:])
            return s

    class WAMPJSONEncoder(json_lib.Encoder):
        def default(self, obj: Any):
            if isinstance(obj, ByteString):
                return (
                    JSON_PACKED_BYTES_PREFIX
                    + b64encode(obj).decode('ascii')
                )
            raise TypeError(f'{obj} is not JSON serializable')

    deserialize = WAMPJSONDecoder()
    serialize = WAMPJSONEncoder()

elif JSON_LIBRARY == 'orjson':
    warnings.warn('Found orjson library for JSON serialization. Binary value '
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
