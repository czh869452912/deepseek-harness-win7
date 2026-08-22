"""
Workspace Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/workspace.schema`).
1:1 with reference `api/workspace.schema.ts`.
"""

from typing import Any, Dict, List, Tuple


def _issue(path, message, code="invalid_type"):
    return {"code": code, "path": list(path), "message": message}


def validate_workspace_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
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
    if method == "list":
        if payload:
            # should be empty
            if any(k not in [] for k in payload.keys()):
                # allow empty but not fail
                pass
        return []
    if method == "create":
        if "path" not in payload or not isinstance(payload.get("path"), str):
            return [_issue(["path"], "path must be string")]
        return []
    if method == "rename":
        issues = []
        wid = payload.get("workspaceId")
        if not isinstance(wid, str) or not wid.strip():
            issues.append(_issue(["workspaceId"], "workspaceId must be non-empty string"))
        title = payload.get("title")
        if not isinstance(title, str):
            issues.append(_issue(["title"], "title must be string"))
        elif not title.strip():
            issues.append(_issue(["title"], "workspace.rename requires a non-blank title"))
        return issues
    if method == "delete":
        wid = payload.get("workspaceId")
        if not isinstance(wid, str) or not wid.strip():
            return [_issue(["workspaceId"], "workspaceId must be non-empty string")]
        return []
    if method == "insertBefore":
        issues = []
        wid = payload.get("workspaceId")
        if not isinstance(wid, str) or not wid.strip():
            issues.append(_issue(["workspaceId"], "workspaceId must be non-empty string"))
        if "beforeWorkspaceId" in payload and payload["beforeWorkspaceId"] is not None:
            b = payload["beforeWorkspaceId"]
            if not isinstance(b, str) or not b.strip():
                issues.append(_issue(["beforeWorkspaceId"], "beforeWorkspaceId must be non-empty string"))
        return issues
    if method == "insertSessionBefore":
        issues = []
        for k in ("workspaceId", "sessionId"):
            v = payload.get(k)
            if not isinstance(v, str) or not v.strip():
                issues.append(_issue([k], f"{k} must be non-empty string"))
        if "beforeSessionId" in payload and payload["beforeSessionId"] is not None:
            b = payload["beforeSessionId"]
            if not isinstance(b, str) or not b.strip():
                issues.append(_issue(["beforeSessionId"], "beforeSessionId must be non-empty string"))
        return issues
    if method == "archiveSession":
        sid = payload.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            return [_issue(["sessionId"], "sessionId must be non-empty string")]
        return []
    return []
