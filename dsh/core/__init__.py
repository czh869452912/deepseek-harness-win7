"""
Core Subsystems: Session, System Prompt, Tools, Agent Loop, Scope
"""

from dsh.core.agent import Agent, AgentHandle, AgentOptions, AgentPlugin, AgentRegistry, CancelOptions
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService, BlockAssembler
from dsh.core.consumed_work import ConsumedWork, fold_consumed_work
from dsh.core.inbox import Inbox
from dsh.core.model_selection import ModelSelection, ModelSelectionRef, install_model_selection
from dsh.core.runtime_context import RuntimeContextProjection
from dsh.core.session import Session, SessionHeader, SessionPlugin, SessionPreparation, SessionStore, canonical_header, header_equals
from dsh.core.surface import SurfaceManager

__all__ = [
    "Agent",
    "AgentHandle",
    "AgentOptions",
    "CancelOptions",
    "AgentRegistry",
    "AgentPlugin",
    "AgentLoopService",
    "AgentLoopPlugin",
    "BlockAssembler",
    "ConsumedWork",
    "fold_consumed_work",
    "Inbox",
    "ModelSelection",
    "ModelSelectionRef",
    "install_model_selection",
    "RuntimeContextProjection",
    "Session",
    "SessionHeader",
    "SessionPreparation",
    "SessionStore",
    "SessionPlugin",
    "canonical_header",
    "header_equals",
    "SurfaceManager",
]
