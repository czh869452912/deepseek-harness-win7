"""
Structural secret redaction for settings values.
Aligned 1:1 with reference @deepseek-ai/dsh-settings/redact.
"""

from typing import Any, Dict, List, Optional


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
    return isinstance(value, dict)


def _get_node_properties(node: Any) -> Dict[str, Any]:
    if isinstance(node, dict):
        return node.get("dict") or node.get("properties") or {}
    dict_val = getattr(node, "dict", None)
    if isinstance(dict_val, dict):
        return dict_val
    props_val = getattr(node, "properties", None)
    if isinstance(props_val, dict):
        return props_val
    return {}


def _get_node_role(node: Any) -> Optional[str]:
    if isinstance(node, dict):
        meta = node.get("meta")
        if isinstance(meta, dict) and "role" in meta:
            return str(meta["role"])
        if "role" in node:
            return str(node["role"])
        return None
    meta = getattr(node, "meta", None)
    if meta is not None:
        role = getattr(meta, "role", None)
        if role is not None:
            return str(role)
        if isinstance(meta, dict) and "role" in meta:
            return str(meta["role"])
    role = getattr(node, "role", None)
    if role is not None:
        return str(role)
    return None


def _get_node_type(node: Any) -> Optional[str]:
    if isinstance(node, dict):
        return node.get("type")
    return getattr(node, "type", None)


def _get_node_inner(node: Any) -> Any:
    if isinstance(node, dict):
        return node.get("inner") or node.get("value")
    return getattr(node, "inner", None) or getattr(node, "value", None)


def _walk(node: Any, value: Any, path: List[str], secrets: List[RedactedSecret]) -> Any:
    role = _get_node_role(node)
    if role == "secret":
        secrets.append(RedactedSecret(path=list(path), set_flag=(value is not None and value != "")))
        return None

    node_type = _get_node_type(node)

    if node_type == "object" or (node_type is None and is_record(value)):
        properties = _get_node_properties(node)
        source = value if is_record(value) else None
        rebuilt: Dict[str, Any] = {}

        if source is not None:
            for key, entry in source.items():
                if properties and key in properties:
                    continue
                # Heuristic for secret keys if no explicit schema properties
                if not properties and key in ("apiKey", "api_key", "secret", "password", "token"):
                    secrets.append(RedactedSecret(path=path + [str(key)], set_flag=bool(entry)))
                else:
                    rebuilt[key] = entry

        if properties:
            for key, child in properties.items():
                child_val = source.get(key) if source is not None else None
                stripped = _walk(child, child_val, path + [str(key)], secrets)
                if stripped is not None:
                    rebuilt[key] = stripped

        if source is None and len(rebuilt) == 0:
            return value
        return rebuilt

    elif node_type == "dict":
        if not is_record(value):
            return value
        inner = _get_node_inner(node)
        rebuilt_dict: Dict[str, Any] = {}
        for key, entry in value.items():
            stripped = _walk(inner, entry, path + [str(key)], secrets)
            if stripped is not None:
                rebuilt_dict[key] = stripped
        return rebuilt_dict

    elif node_type == "array":
        if not isinstance(value, list):
            return value
        inner = _get_node_inner(node)
        return [
            _walk(inner, entry, path + [str(i)], secrets)
            for i, entry in enumerate(value)
        ]

    return value


def redact_secrets(schema: Any, value: Any) -> RedactedValue:
    """
    Remove every role('secret') field a schema declares from a value.
    The input is never mutated.
    Returns RedactedValue carrying stripped value and ordered secret positions.
    """
    secrets: List[RedactedSecret] = []
    stripped = _walk(schema, value, [], secrets)
    return RedactedValue(value=stripped, secrets=secrets)
