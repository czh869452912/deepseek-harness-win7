import pytest
from dsh.cordis.context import Context
from dsh.interaction.commands import CommandRegistry
from dsh.core.session import Session

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
    cmd_svc = CommandRegistry(ctx)
    ctx.set_service("commands", cmd_svc)

    compaction_svc = DummyCompactionService()
    ctx.set_service("compaction", compaction_svc)

    await ctx.registry.plugin(CommandCompactPlugin, parent_ctx=ctx)
    assert cmd_svc.has("compact")

    sess = Session("test-session")
    res = await cmd_svc.execute("compact", sess, [])
    assert "Compaction completed" in res
    assert "Shadowed 3 events" in res
    assert compaction_svc.compact_called

