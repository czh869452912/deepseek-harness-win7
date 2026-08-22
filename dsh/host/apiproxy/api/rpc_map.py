"""
RPC Method Map Registry (`@deepseek-ai/dsh-apiproxy/api/rpc-map`).
Full 43 official Unary RPC methods catalog aligned 1:1 with reference `api/rpc-map.ts`.
"""

from typing import Set

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
}
