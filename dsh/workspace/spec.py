"""
The workspace domain declaration: record schema and domain spec.
Aligned 1:1 with official `@deepseek-ai/dsh-workspace/src/spec`.
"""

from typing import Any, Dict
from dsh.storage.domain_spec import DomainGlobalSpec, DomainSpec, define_domain, domain_table, SchemaValidator


def _parse_workspace_record(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("workspace record must be an object")
    if not isinstance(data.get("path"), str):
        raise ValueError("workspace record path must be a string")
    if not isinstance(data.get("title"), str):
        raise ValueError("workspace record title must be a string")
    if not isinstance(data.get("sessionIds"), list):
        raise ValueError("workspace record sessionIds must be an array")
    if not isinstance(data.get("createdAt"), str):
        raise ValueError("workspace record createdAt must be a string")
    if not isinstance(data.get("updatedAt"), str):
        raise ValueError("workspace record updatedAt must be a string")
    return {
        "path": data["path"],
        "title": data["title"],
        "sessionIds": [str(s) for s in data["sessionIds"]],
        "createdAt": data["createdAt"],
        "updatedAt": data["updatedAt"],
    }


workspace_record = SchemaValidator(_parse_workspace_record)
workspaceRecord = workspace_record


def _parse_workspace_domain_state(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("workspace domain state must be an object")
    if not isinstance(data.get("initialized"), bool):
        raise ValueError("workspace domain state initialized must be a boolean")
    if not isinstance(data.get("workspaceIds"), list):
        raise ValueError("workspace domain state workspaceIds must be an array")
    archived = data.get("archivedSessionIds", [])
    if not isinstance(archived, list):
        raise ValueError("workspace domain state archivedSessionIds must be an array")
    pending = data.get("pendingMutation")
    if pending is not None and not isinstance(pending, dict):
        raise ValueError("workspace domain state pendingMutation must be an object")

    return {
        "initialized": data["initialized"],
        "workspaceIds": [str(w) for w in data["workspaceIds"]],
        "archivedSessionIds": [str(s) for s in archived],
        "pendingMutation": pending,
    }


workspace_domain_state = SchemaValidator(_parse_workspace_domain_state)
workspaceDomainState = workspace_domain_state

workspace_domain_spec = define_domain(
    name="workspace",
    version=2,
    global_spec=DomainGlobalSpec(
        schema=workspace_domain_state,
        initial={
            "initialized": False,
            "workspaceIds": [],
            "archivedSessionIds": [],
            "pendingMutation": None,
        },
    ),
    tables={"workspaces": domain_table(workspace_record)},
)

workspaceDomainSpec = workspace_domain_spec
