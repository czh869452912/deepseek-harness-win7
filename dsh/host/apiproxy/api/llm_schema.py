"""
LLM Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/llm.schema`).
1:1 with reference `api/llm.schema.ts`.
"""

from typing import Any, Dict, List, Tuple


def _issue(path, message, code="invalid_type"):
    return {"code": code, "path": list(path), "message": message}


def validate_llm_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Payload must be an object"
    # dispatch by method suffix
    m = method.split(".")[-1].split("/")[-1] if method else ""
    if m in ("providers", "models"):
        # empty object - any extra keys are ignored (z.object({}) strict? but allow empty)
        if payload and not isinstance(payload, dict):
            return False, "providers/models payload must be object"
        return True, ""
    if m in ("discoverModels", "discover_models"):
        issues: List[Dict[str, Any]] = []
        # settingsNs min(1)
        ns = payload.get("settingsNs")
        if not isinstance(ns, str) or not ns.strip():
            issues.append(_issue(["settingsNs"], "settingsNs must be non-empty string"))
        for k in ("provider", "baseURL", "base_url", "api", "apiKey", "api_key"):
            if k in payload and payload[k] is not None:
                v = payload[k]
                if not isinstance(v, str) or not v.strip():
                    issues.append(_issue([k], f"{k} must be non-empty string if provided"))
        if issues:
            return False, str(issues)
        return True, ""
    return True, ""


def validate_llm_providers_payload(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict) or payload:
        # should be empty
        if isinstance(payload, dict) and len(payload) == 0:
            return []
        return [_issue([], "providers request must be empty object")]
    return []


def validate_llm_discover_payload(payload: Any) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        return [_issue([], "payload must be object")]
    ns = payload.get("settingsNs")
    if not isinstance(ns, str) or not ns.strip():
        issues.append(_issue(["settingsNs"], "settingsNs must be non-empty string", "too_small"))
    for k in ("provider", "baseURL", "api", "apiKey"):
        if k in payload and payload[k] is not None:
            v = payload[k]
            if not isinstance(v, str) or not v.strip():
                issues.append(_issue([k], f"{k} must be non-empty string"))
    return issues
