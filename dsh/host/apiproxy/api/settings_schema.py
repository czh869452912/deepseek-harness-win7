"""
Settings Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/settings.schema`).
1:1 with reference `api/settings.schema.ts`.
"""

from typing import Any, Dict, List, Tuple


def _issue(path, message, code="invalid_type"):
    return {"code": code, "path": list(path), "message": message}


def validate_settings_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    m = method.split(".")[-1].split("/")[-1] if method else ""
    issues = validate_by_method(m, payload)
    if issues:
        return False, str(issues)
    return True, ""


def validate_by_method(method: str, payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return [_issue([], "payload must be object")]
    if method in ("describe", "openDocument", "open_document"):
        # empty object
        return []
    if method == "update":
        issues: List[Dict[str, Any]] = []
        ns = payload.get("ns")
        if not isinstance(ns, str) or not ns.strip():
            issues.append(_issue(["ns"], "ns must be non-empty string"))
        patch = payload.get("patch")
        if not isinstance(patch, dict):
            issues.append(_issue(["patch"], "patch must be object"))
        if "expectedRevision" in payload and payload["expectedRevision"] is not None and not isinstance(payload["expectedRevision"], (int, float)):
            issues.append(_issue(["expectedRevision"], "expectedRevision must be number"))
        return issues
    if method == "replace":
        issues = []
        ns = payload.get("ns")
        if not isinstance(ns, str) or not ns.strip():
            issues.append(_issue(["ns"], "ns must be non-empty string"))
        section = payload.get("section")
        if not isinstance(section, dict):
            issues.append(_issue(["section"], "section must be object"))
        if "expectedRevision" in payload and payload["expectedRevision"] is not None and not isinstance(payload["expectedRevision"], (int, float)):
            issues.append(_issue(["expectedRevision"], "expectedRevision must be number"))
        return issues
    if method == "mutate":
        issues = []
        ns = payload.get("ns")
        if not isinstance(ns, str) or not ns.strip():
            issues.append(_issue(["ns"], "ns must be non-empty string"))
        ops = payload.get("ops")
        if not isinstance(ops, list):
            issues.append(_issue(["ops"], "ops must be array"))
        else:
            for i, op in enumerate(ops):
                if not isinstance(op, dict):
                    issues.append(_issue(["ops", i], "op must be object"))
                    continue
                kind = op.get("op")
                if kind not in ("set", "unset"):
                    issues.append(_issue(["ops", i, "op"], "op must be set|unset"))
                path = op.get("path")
                if not isinstance(path, list) or any(not isinstance(p, str) for p in path):
                    issues.append(_issue(["ops", i, "path"], "path must be array of strings"))
                if kind == "set" and "value" not in op:
                    issues.append(_issue(["ops", i, "value"], "set requires value"))
        if "expectedRevision" in payload and payload["expectedRevision"] is not None and not isinstance(payload["expectedRevision"], (int, float)):
            issues.append(_issue(["expectedRevision"], "expectedRevision must be number"))
        return issues
    return []
