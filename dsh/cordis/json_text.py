"""ECMAScript JSON text for Python representations of plain JSON data."""
import json
import re

from dsh.cordis.utils import _js_number_to_string, _js_own_enumerable_keys


_SURROGATE = re.compile(r"[\ud800-\udfff]")


def normalize_json_string(value):
    return value.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def _can_encode_directly(value):
    kind = type(value)
    if kind is str:
        return _SURROGATE.search(value) is None
    if value is None or kind is bool:
        return True
    if kind is int:
        return -9007199254740992 <= value <= 9007199254740992
    if kind is list:
        for item in value:
            if not _can_encode_directly(item):
                return False
        return True
    if kind is dict:
        for key, item in value.items():
            # An ASCII digit can start an ECMAScript array index. Those
            # objects need the compatibility encoder's key ordering.
            if (type(key) is not str or (key and "0" <= key[0] <= "9")
                    or _SURROGATE.search(key) or not _can_encode_directly(item)):
                return False
        return True
    return False


def stringify_json(value):
    if type(value) in (dict, list) and _can_encode_directly(value):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return _stringify_compatible(value)


def _stringify_compatible(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = _js_number_to_string(value)
        return "null" if number in ("NaN", "Infinity", "-Infinity") else number
    if isinstance(value, str):
        if type(value) is str and _SURROGATE.search(value) is None:
            return json.encoder.encode_basestring(value)
        rendered = json.dumps(normalize_json_string(value), ensure_ascii=False)
        return rendered.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, list):
        return "[" + ",".join(_stringify_compatible(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON data must have string keys")
        normalized = {normalize_json_string(key): item for key, item in value.items()}
        return "{" + ",".join(_stringify_compatible(key) + ":" + _stringify_compatible(normalized[key])
                              for key in _js_own_enumerable_keys(normalized)) + "}"
    raise TypeError("expected plain JSON data")
