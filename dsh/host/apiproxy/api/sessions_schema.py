"""
Sessions Domain Schema Validation (`@deepseek-ai/dsh-apiproxy/api/sessions.schema`).
1:1 with reference `api/sessions.schema.ts`.
"""

from typing import Any, Dict, List, Tuple


def _issue(path, message, code="invalid_type"):
    return {"code": code, "path": list(path), "message": message}


def validate_session_payload(method: str, payload: Dict[str, Any]) -> Tuple[bool, str]:
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
        # cursor optional string
        if "cursor" in payload and payload["cursor"] is not None and not isinstance(payload["cursor"], str):
            return [_issue(["cursor"], "cursor must be string")]
        return []
    if method == "create":
        issues: List[Dict[str, Any]] = []
        if "workspaceId" in payload and payload["workspaceId"] is not None and (not isinstance(payload["workspaceId"], str) or not payload["workspaceId"].strip()):
            issues.append(_issue(["workspaceId"], "workspaceId must be non-empty string"))
        if "cwd" in payload and payload["cwd"] is not None and not isinstance(payload["cwd"], str):
            issues.append(_issue(["cwd"], "cwd must be string"))
        if "sessionId" in payload and payload["sessionId"] is not None and (not isinstance(payload["sessionId"], str) or not payload["sessionId"].strip()):
            issues.append(_issue(["sessionId"], "sessionId must be non-empty string"))
        if "agentPreset" in payload and payload["agentPreset"] is not None and (not isinstance(payload["agentPreset"], str) or not payload["agentPreset"].strip()):
            issues.append(_issue(["agentPreset"], "agentPreset must be non-empty string"))
        if payload.get("workspaceId") is not None and payload.get("cwd") is not None:
            issues.append(_issue([], "session.create accepts workspaceId or cwd, not both"))
        return issues
    if method == "rename":
        issues = []
        sid = payload.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            issues.append(_issue(["sessionId"], "sessionId must be non-empty string"))
        if "title" not in payload or not isinstance(payload.get("title"), str):
            issues.append(_issue(["title"], "title must be string"))
        return issues
    if method == "fork":
        issues = []
        sid = payload.get("sessionId") or payload.get("sourceSessionId")
        if not isinstance(sid, str) or not sid.strip():
            issues.append(_issue(["sessionId"], "sessionId must be non-empty string"))
        if "atSeq" in payload and payload["atSeq"] is not None:
            at = payload["atSeq"]
            if not isinstance(at, int) or at < 0:
                issues.append(_issue(["atSeq"], "atSeq must be non-negative integer"))
        return issues
    if method == "history":
        issues = []
        sid = payload.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            issues.append(_issue(["sessionId"], "sessionId must be non-empty string"))
        if "beforeSeq" in payload and payload["beforeSeq"] is not None:
            b = payload["beforeSeq"]
            if not isinstance(b, int) or b < 0:
                issues.append(_issue(["beforeSeq"], "beforeSeq must be non-negative integer"))
        if "maxMessages" in payload and payload["maxMessages"] is not None:
            m = payload["maxMessages"]
            if not isinstance(m, int) or m <= 0:
                issues.append(_issue(["maxMessages"], "maxMessages must be positive integer"))
        return issues
    if method in ("models",):
        sid = payload.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            return [_issue(["sessionId"], "sessionId must be non-empty string")]
        return []
    if method in ("selectModel", "select_model"):
        issues = []
        for k in ("sessionId", "provider", "model"):
            v = payload.get(k)
            if not isinstance(v, str) or not v.strip():
                issues.append(_issue([k], f"{k} must be non-empty string"))
        if "reasoningEffort" in payload and payload["reasoningEffort"] is not None:
            v = payload["reasoningEffort"]
            if not isinstance(v, str) or not v.strip():
                issues.append(_issue(["reasoningEffort"], "reasoningEffort must be non-empty string"))
        return issues
    if method == "prompt":
        issues = []
        sid = payload.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            issues.append(_issue(["sessionId"], "sessionId must be non-empty string"))
        mode = payload.get("mode")
        if mode not in ("queue", "steer"):
            issues.append(_issue(["mode"], "mode must be 'queue' or 'steer'"))
        content = payload.get("content")
        if not isinstance(content, list):
            issues.append(_issue(["content"], "content must be array"))
        else:
            for i, part in enumerate(content):
                if not isinstance(part, dict) or "type" not in part:
                    issues.append(_issue(["content", i], "content part must be object with type"))
                    continue
                t = part.get("type")
                if t == "text":
                    if not isinstance(part.get("text"), str):
                        issues.append(_issue(["content", i, "text"], "text must be string"))
                elif t == "image":
                    if part.get("mediaType") not in ("image/png", "image/jpeg", "image/webp", "image/gif"):
                        issues.append(_issue(["content", i, "mediaType"], "invalid mediaType"))
                    if not isinstance(part.get("data"), str) or not part.get("data"):
                        issues.append(_issue(["content", i, "data"], "image data must be non-empty string"))
                else:
                    issues.append(_issue(["content", i, "type"], "unknown content type"))
        if "clientTimeZone" in payload and payload["clientTimeZone"] is not None and not isinstance(payload["clientTimeZone"], str):
            issues.append(_issue(["clientTimeZone"], "clientTimeZone must be string"))
        return issues
    if method == "attachment":
        issues = []
        for k in ("sessionId", "attachmentId"):
            v = payload.get(k)
            if not isinstance(v, str) or not v.strip():
                issues.append(_issue([k], f"{k} must be non-empty string"))
        return issues
    if method == "updateQueue":
        issues = []
        for k in ("sessionId", "itemId"):
            v = payload.get(k)
            if not isinstance(v, str) or not v.strip():
                issues.append(_issue([k], f"{k} must be non-empty string"))
        action = payload.get("action")
        if not isinstance(action, dict) or "kind" not in action:
            issues.append(_issue(["action"], "action must be object with kind"))
        else:
            kind = action.get("kind")
            if kind not in ("edit", "remove", "steer"):
                issues.append(_issue(["action", "kind"], "kind must be edit|remove|steer"))
            if kind == "edit" and not isinstance(action.get("content"), list):
                issues.append(_issue(["action", "content"], "edit requires content array"))
        return issues
    if method == "cancel":
        sid = payload.get("sessionId")
        if not isinstance(sid, str) or not sid.strip():
            return [_issue(["sessionId"], "sessionId must be non-empty string")]
        return []
    if method == "search":
        q = payload.get("query")
        if not isinstance(q, str) or not q.strip():
            return [_issue(["query"], "query must be non-empty string")]
        if len(q.strip()) > 500:
            return [_issue(["query"], "query exceeds 500 chars")]
        if "\0" in q:
            return [_issue(["query"], "search query must not contain NUL")]
        return []
    return []
