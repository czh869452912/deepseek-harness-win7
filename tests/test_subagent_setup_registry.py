import pytest

from dsh.cordis.context import Context
from dsh.subagent.setup_registry import SetupRegistry
from dsh.subagent.errors import SubagentError


@pytest.mark.asyncio
async def test_setup_revocation_fences_pending_publication_and_releases_every_installation():
    registry, first, second = SetupRegistry(), Context(), Context()
    released = []
    dispose = registry.register(lambda child: lambda: released.append(child))
    one, two = registry.apply(first), registry.apply(second)
    one.commit()
    dispose()
    assert released == [first, second]
    with pytest.raises(SubagentError) as error:
        two.commit()
    assert error.value.code == "ACTIVATION_SETUP_REVOKED"
    await first.fiber.dispose()
    await second.fiber.dispose()
    assert len(released) == 2 and registry.children == {}


@pytest.mark.asyncio
async def test_self_revocation_during_installation_rolls_back_escaped_grant():
    registry, ctx = SetupRegistry(), Context()
    released = []
    def contribution(child):
        dispose()
        return lambda: released.append("released")
    dispose = registry.register(contribution)
    commit = registry.apply(ctx)
    with pytest.raises(SubagentError):
        commit.commit()
    assert released == ["released"]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_disposal_fault_does_not_leave_other_children_granted():
    registry, first, second = SetupRegistry(), Context(), Context()
    released = []
    def contribution(child):
        def release():
            released.append(child)
            raise RuntimeError("release fault")
        return release
    dispose = registry.register(contribution)
    registry.apply(first).commit()
    registry.apply(second).commit()
    with pytest.raises(SubagentError, match="2 installation"):
        dispose()
    assert released == [first, second] and registry.children == {}
    await first.fiber.dispose()
    await second.fiber.dispose()
