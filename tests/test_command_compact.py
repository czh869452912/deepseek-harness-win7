import pytest
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.agent import Agent
from dsh.interaction.commands import CommandsPlugin
from dsh.core.session import SessionStore

from dsh.compaction.command_compact import CommandCompactPlugin


class DummyCompactionService:
    def __init__(self):
        self.compact_called = False

    async def compact_now(self, agent):
        self.compact_called = True
        return {"shadowedSeqs": [0, 1, 2]}


@pytest.mark.asyncio
async def test_command_compact_execution():
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(CommandsPlugin)

    compaction_svc = DummyCompactionService()
    ctx.set_service("compaction", compaction_svc)

    await ctx.plugin(CommandCompactPlugin)
    session = ctx.get("sessions").create("test-session")
    agent = Agent(session=session, ctx=ctx, agent_id="test-session")
    assert ctx.commands.find(agent, "compact") is not None

    execution = await ctx.commands.execute(agent, "/compact", [], AbortController().signal)
    assert "Compaction completed" in execution.result["text"]
    assert "Shadowed 3 events" in execution.result["text"]
    assert compaction_svc.compact_called


@pytest.mark.asyncio
async def test_command_compact_reports_a_missing_compaction_service():
    """
    The registered handler reports the unmounted capability instead of raising,
    matching `reference/packages/compaction/command-compact/src/index.ts`.
    """
    ctx = Context()
    await ctx.plugin(SessionStore)
    await ctx.plugin(CommandsPlugin)
    await ctx.plugin(CommandCompactPlugin)
    session = ctx.get("sessions").create("no-compaction")
    agent = Agent(session=session, ctx=ctx, agent_id="no-compaction")

    execution = await ctx.commands.execute(agent, "/compact", [], AbortController().signal)
    assert execution.result["kind"] == "error"
    assert "Compaction service is not mounted" in execution.result["text"]
