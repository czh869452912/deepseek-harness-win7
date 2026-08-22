"""
Fetch Carrier & Unary RPC Handler (`@deepseek-ai/dsh-host-apiproxy/fetch`).
Maps incoming HTTP Requests onto ApiProxy RPC methods and handles SSE/Download GET routes.
1:1 aligned with reference `fetch/handler.ts`.
"""

import json
import uuid
from typing import Any, Callable, Dict, Optional, Set

OFFICIAL_RPC_METHODS: Set[str] = {
    "session.list", "session.search", "session.create", "session.history",
    "session.models", "session.selectModel", "session.rename", "session.fork",
    "session.prompt", "session.attachment", "session.updateQueue", "session.cancel",
    "subagent.list", "subagent.history", "subagent.prompt", "subagent.interrupt",
    "host.describe", "host.pickDirectory", "host.listDirectory", "host.createDirectory", "host.openPath",
    "workspace.list", "workspace.create", "workspace.rename", "workspace.delete",
    "workspace.insertBefore", "workspace.insertSessionBefore", "workspace.archiveSession", "workspace.files",
    "skill.list",
    "agentPreset.list", "agentPreset.select", "agentPreset.read", "agentPreset.copy",
    "agentPreset.openDocument", "agentPreset.remove",
    "goal.create", "goal.edit", "goal.pause", "goal.resume", "goal.complete", "goal.clear",
    "settings.describe", "settings.openDocument", "settings.update", "settings.replace", "settings.mutate",
    "credentials.describe", "credentials.set", "credentials.unset",
    "llm.providers", "llm.models", "llm.discoverModels",
    "jobs.list", "pluginInventory.list"
}

INVALID_REQUEST_RPC_ID = "invalid-request"


def normalize_rpc_method(path: str) -> str:
    """Extract raw RPC method string from `/api/...` path."""
    raw = path[5:] if path.startswith("/api/") else path
    # handle slashes like session/list -> session.list
    if "/" in raw and not raw.startswith("events"):
        parts = raw.split("/", 1)
        if len(parts) == 2:
            candidate = f"{parts[0]}.{parts[1]}"
            if candidate in OFFICIAL_RPC_METHODS:
                return candidate
    return raw


def method_for(path: str) -> Optional[str]:
    """Route lookup that narrows path to official RPC method name."""
    norm = normalize_rpc_method(path)
    if norm in OFFICIAL_RPC_METHODS:
        return norm
    # fallback aliases
    aliases = {
        "settings": "settings.describe",
        "models": "llm.models",
        "sessions": "session.list",
    }
    return aliases.get(norm)
