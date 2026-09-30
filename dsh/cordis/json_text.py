"""ECMAScript JSON text for Python representations of plain JSON data."""
import json

from dsh.cordis.utils import _js_number_to_string, _js_own_enumerable_keys


def normalize_json_string(value):
    return value.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def stringify_json(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        number = _js_number_to_string(value)
        return "null" if number in ("NaN", "Infinity", "-Infinity") else number
    if isinstance(value, str):
        rendered = json.dumps(normalize_json_string(value), ensure_ascii=False)
        return rendered.encode("utf-8", "backslashreplace").decode("utf-8")
    if isinstance(value, list):
        return "[" + ",".join(stringify_json(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("JSON data must have string keys")
        normalized = {normalize_json_string(key): item for key, item in value.items()}
        return "{" + ",".join(stringify_json(key) + ":" + stringify_json(normalized[key])
                              for key in _js_own_enumerable_keys(normalized)) + "}"
    raise TypeError("expected plain JSON data")
