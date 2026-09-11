"""
1:1 Test for dsh-agent-loop-testkit.
Ported from reference packages/test-support/agent-loop-testkit/tests/agent-loop-testkit.spec.ts.
Compatible with Python 3.8.10 and Windows 7 SP1.
"""

import pytest

from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoop
from dsh.core.system_prompt import render_prompt
from .agent_loop_testkit import mount_agent_loop_test_dependencies, mountAgentLoopTestDependencies



@pytest.mark.asyncio
async def test_agent_loop_testkit_mounts_spine_that_can_activate_agent_loop():
    ctx = Context()
    try:
        await mountAgentLoopTestDependencies(ctx, {
            "systemPrompt": {"persona": "Test persona."},
            "tools": {"mode": "native"},
        })

        system_prompt = ctx.get("systemPrompt")
        assembled = await system_prompt.assemble()
        assert "Test persona." in render_prompt(assembled)

        fiber = await ctx.plugin(AgentLoop, {"agents": []})
        assert fiber is not None

    finally:
        await ctx.fiber.dispose()
