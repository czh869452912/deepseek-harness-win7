"""
Fetch Carrier & Unary RPC Handler (`@deepseek-ai/dsh-host-apiproxy/fetch`).
Maps incoming HTTP Requests onto ApiProxy RPC methods and handles SSE/Download GET routes.
Aligned 1:1 with reference `fetch/handler.ts`.
"""

import json
from typing import Any, Callable, Dict, Optional, Set
import urllib.parse

from dsh.host.apiproxy.native_path_opener import open_native_path
from dsh.host.apiproxy.session_export import export_session_ndjson, export_session_zip
from dsh.host.webserver.webserver import HttpResponseWriter

# Complete 1:1 list of official Unary RPC methods from handler.ts
OFFICIAL_RPC_METHODS: Set[str] = {
    # Session domain
    "session.list", "session.search", "session.create", "session.history",
    "session.models", "session.selectModel", "session.rename", "session.fork",
    "session.prompt", "session.attachment", "session.updateQueue", "session.cancel",
    # Subagent domain
    "subagent.list", "subagent.history", "subagent.prompt", "subagent.interrupt",
    # Host domain
    "host.describe", "host.pickDirectory", "host.listDirectory", "host.createDirectory", "host.openPath",
    # Workspace domain
    "workspace.list", "workspace.create", "workspace.rename", "workspace.delete",
    "workspace.insertBefore", "workspace.insertSessionBefore", "workspace.archiveSession", "workspace.files",
    # Skill domain
    "skill.list",
    # Agent Preset domain
    "agentPreset.list", "agentPreset.select", "agentPreset.read", "agentPreset.copy",
    "agentPreset.openDocument", "agentPreset.remove",
    # Goal domain
    "goal.create", "goal.edit", "goal.pause", "goal.resume", "goal.complete", "goal.clear",
    # Settings domain
    "settings.describe", "settings.openDocument", "settings.update", "settings.replace", "settings.mutate",
    # Credentials domain
    "credentials.describe", "credentials.set", "credentials.unset",
    # LLM domain
    "llm.providers", "llm.models", "llm.discoverModels",
    # Jobs domain
    "jobs.list",
    # Plugin inventory domain
    "pluginInventory.list",
}


def normalize_rpc_method(path: str) -> str:
    """Extract raw RPC method string from `/api/...` path."""
    return path[5:] if path.startswith("/api/") else path
