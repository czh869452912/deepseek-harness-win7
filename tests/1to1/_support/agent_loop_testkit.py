"""
Agent Loop Testkit: Shared mounting for prerequisite services required before tests load concrete agent loop.
Ported 1:1 from reference packages/test-support/agent-loop-testkit/src/index.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

from typing import Any, Dict, Optional

from dsh.cordis.context import Context
from dsh.core.agent import AgentRegistry
from dsh.core.session import SessionStore
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolRuntime
from dsh.llm.llm_service import LlmRuntime


PACKAGE_NAME = "@deepseek-ai/dsh-agent-loop-testkit"


async def mount_agent_loop_test_dependencies(
    ctx: Context,
    options: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Mount the standard prerequisite services for an AgentLoop test.

    The function deliberately does not mount AgentLoop or register an adapter,
    so tests retain control of load order and the topology under test. The
    context owns every mounted service and remains responsible for disposal.
    """
    opts = options or {}
    sp_config = opts.get("systemPrompt") if "systemPrompt" in opts else opts.get("system_prompt", {})
    tools_config = opts.get("tools", {})

    await ctx.plugin(LlmRuntime)
    await ctx.plugin(SessionStore)
    await ctx.plugin(SystemPrompt, sp_config or {})
    await ctx.plugin(ToolRuntime, tools_config or {})
    await ctx.plugin(AgentRegistry)


mountAgentLoopTestDependencies = mount_agent_loop_test_dependencies

name = "agent-loop-testkit-invariant"
inject = ["invariants"]


def install():
    pass


def apply(ctx: Context):
    invariants = ctx.get("invariants")
    if invariants and hasattr(invariants, "register"):
        return invariants.register(PACKAGE_NAME, install)
    return lambda: None
