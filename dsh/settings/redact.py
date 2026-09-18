"""
Structural secret redaction for settings values.
Aligned 1:1 with reference @deepseek-ai/dsh-settings/redact.

Language adaptation: JavaScript `undefined` has no Python value, so the walk
reads an absent field as the port's undefined sentinel (`dsh.cordis.utils`).
`RedactedSecret.set` is `value !== undefined` in the reference, so a stored
JSON `null` counts as set while an absent field does not; only the sentinel can
tell those apart.
"""

from typing import Any, Dict, List, Optional

from dsh.cordis.utils import _UNDEFINED


class RedactedSecret:
    """One schema-declared secret position inside a redacted value."""

    def __init__(self, path: List[str], set_flag: bool):
        self.path = path
        self.set = set_flag

    def to_dict(self) -> Dict[str, Any]:
        return {"path": self.path, "set": self.set}

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, RedactedSecret):
            return self.path == other.path and self.set == other.set
        if isinstance(other, dict):
            return self.path == other.get("path") and self.set == other.get("set")
        return False

    def __repr__(self) -> str:
        return f"RedactedSecret(path={self.path}, set={self.set})"


class RedactedValue:
    """A value with every role('secret') field removed, plus the removal record."""

    def __init__(self, value: Any, secrets: List[RedactedSecret]):
        self.value = value
        self.secrets = secrets


def is_record(value: Any) -> bool:
    """Whether a value is a plain data object the walker may recurse into."""
    return isinstance(value, dict)


def _node_member(node: Any, key: str) -> Any:
    """Read one structural member of a live schema node (or of its mapping form)."""
    if isinstance(node, dict):
        return node.get(key, _UNDEFINED)
    return getattr(node, key, _UNDEFINED)


def _node_role(node: Any) -> Optional[str]:
    """The node's `meta.role`, when it declares one."""
    meta = _node_member(node, "meta")
    if isinstance(meta, dict):
        role = meta.get("role", _UNDEFINED)
    else:
        role = getattr(meta, "role", _UNDEFINED) if meta is not _UNDEFINED else _UNDEFINED
    if role is _UNDEFINED or role is None:
        return None
    return str(role)


def _node_type(node: Any) -> Optional[str]:
    """The node's `type` discriminant."""
    node_type = _node_member(node, "type")
    if node_type is _UNDEFINED or node_type is None:
        return None
    return str(node_type)


def _node_properties(node: Any) -> Dict[str, Any]:
    """An `object` node's property schemas, keyed by property name."""
    properties = _node_member(node, "dict")
    if isinstance(properties, dict):
        return properties
    return {}


def _node_inner(node: Any) -> Any:
    """A `dict`/`array` node's element schema."""
    return _node_member(node, "inner")


def _walk(node: Any, value: Any, path: List[str], secrets: List[RedactedSecret]) -> Any:
    if node is _UNDEFINED or node is None:
        return value
    if _node_role(node) == "secret":
        secrets.append(RedactedSecret(path=list(path), set_flag=value is not _UNDEFINED))
        return _UNDEFINED

    node_type = _node_type(node)

    if node_type == "object":
        properties = _node_properties(node)
        source = value if is_record(value) else _UNDEFINED
        rebuilt: Dict[str, Any] = {}
        if source is not _UNDEFINED:
            for key, entry in source.items():
                if key in properties:
                    continue
                rebuilt[key] = entry
        for key, child in properties.items():
            child_value = source.get(key, _UNDEFINED) if source is not _UNDEFINED else _UNDEFINED
            stripped = _walk(child, child_value, path + [str(key)], secrets)
            if stripped is not _UNDEFINED:
                rebuilt[str(key)] = stripped
        if source is _UNDEFINED and not rebuilt:
            return value
        return rebuilt

    if node_type == "dict":
        if not is_record(value):
            return value
        inner = _node_inner(node)
        rebuilt_dict: Dict[str, Any] = {}
        for key, entry in value.items():
            stripped = _walk(inner, entry, path + [str(key)], secrets)
            if stripped is not _UNDEFINED:
                rebuilt_dict[str(key)] = stripped
        return rebuilt_dict

    if node_type == "array":
        if not isinstance(value, list):
            return value
        inner = _node_inner(node)
        return [
            _walk(inner, entry, path + [str(index)], secrets)
            for index, entry in enumerate(value)
        ]

    return value


def redact_secrets(schema: Any, value: Any) -> RedactedValue:
    """
    Remove every role('secret') field a schema declares from a value.

    The walker follows `object`, `dict`, and `array` containers; a secret must
    be declared directly on a field reachable through those containers. The
    input is never mutated.

    :param schema: live schemastery schema describing the value.
    :param value: the value to strip; an absent value yields an absent result
        with object-property secret slots still enumerated.
    :returns: the stripped detached value and the ordered secret positions.
    """
    secrets: List[RedactedSecret] = []
    stripped = _walk(schema, value, [], secrets)
    return RedactedValue(value=stripped, secrets=secrets)
