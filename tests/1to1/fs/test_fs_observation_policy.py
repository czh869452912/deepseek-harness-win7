"""
1:1 parity suite for `@deepseek-ai/dsh-fs-observation-policy`
(`dsh/fs/fs_observation_policy.py`).

Upstream is reference/packages/fs/fs-observation-policy/tests/policy.spec.ts:
event-level policy tests that need no filesystem provider, because the plugin
performs no I/O. They pin registration/disposal, the write-intent and edit-intent
decisions over the observed-state record, the single-slot first-wins behaviour,
multi-owner isolation, and the state release on disposal.

The reference keys observed state by the opaque JS actor object (a `WeakMap`
key); the port uses the same weak identity on `WeakKeyDictionary`, so the
fixtures are host objects, not mappings.
"""

from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest

from dsh.cordis.context import Context
from dsh.fs.fs_local import FsError, FsTarget
from dsh.fs.fs_observation_policy import FsObservationPolicyPlugin


class _SessionObject:
    """The opaque session identity the observed-state owner map weakly keys on."""


def target(path: str) -> FsTarget:
    return FsTarget(target_key=path, display_path=path)


def owner_exec(session: Any) -> Any:
    return SimpleNamespace(agent=SimpleNamespace(session=session))


def present(version: str) -> Dict[str, Any]:
    return {"kind": "present", "version": version}


ABSENT: Dict[str, Any] = {"kind": "absent"}


async def write_intent(ctx: Context, t: FsTarget, actor: Optional[Any]) -> Any:
    """Dispatch the write-intent waterfall with the bare default thunk."""
    return await ctx.waterfall("fs/write-intent", t, actor, lambda: None)


async def edit_intent(ctx: Context, t: FsTarget, actor: Optional[Any]) -> Any:
    """Dispatch the edit-intent waterfall with the bare default thunk."""
    return await ctx.waterfall("fs/edit-intent", t, actor, lambda: None)


async def setup() -> Dict[str, Any]:
    ctx = Context()
    fiber = await ctx.plugin(FsObservationPolicyPlugin)
    return {"ctx": ctx, "fiber": fiber}


@pytest.mark.asyncio
async def test_registers_no_service_api_it_is_a_plugin_not_a_policy_service():
    test = await setup()
    assert test["ctx"].get("fsPolicy") is None


@pytest.mark.asyncio
async def test_mounts_with_no_inject_and_reads_no_services():
    # It mounts immediately even with nothing else in the context.
    ctx = Context()
    await ctx.plugin(FsObservationPolicyPlugin)
    # The listener is live: an unobserved write decides createIfAbsent.
    assert await write_intent(ctx, target("a.txt"), None) == {"kind": "createIfAbsent"}


@pytest.mark.asyncio
async def test_an_unobserved_target_decides_create_if_absent():
    test = await setup()
    assert await write_intent(test["ctx"], target("a.txt"), owner_exec(_SessionObject())) == {
        "kind": "createIfAbsent"
    }


@pytest.mark.asyncio
async def test_a_no_owner_actor_decides_create_if_absent():
    test = await setup()
    assert await write_intent(test["ctx"], target("a.txt"), None) == {"kind": "createIfAbsent"}
    assert await write_intent(test["ctx"], target("a.txt"), SimpleNamespace()) == {"kind": "createIfAbsent"}


@pytest.mark.asyncio
async def test_an_actor_with_an_agent_but_no_session_has_no_owner():
    # The middle optional-chain rung: agent present, session undefined -> owner
    # undefined -> unobservable, so a write can only be a blind create.
    test = await setup()
    assert await write_intent(test["ctx"], target("a.txt"), SimpleNamespace(agent=SimpleNamespace())) == {
        "kind": "createIfAbsent"
    }


@pytest.mark.asyncio
async def test_an_observed_target_decides_replace_if_version_at_the_observed_version():
    test = await setup()
    exec_ = owner_exec(_SessionObject())
    test["ctx"].emit("fs/observed", target("a.txt"), present("v7"), exec_)
    assert await write_intent(test["ctx"], target("a.txt"), exec_) == {
        "kind": "replaceIfVersion",
        "version": "v7",
    }


@pytest.mark.asyncio
async def test_a_target_observed_absent_decides_create_if_absent():
    test = await setup()
    exec_ = owner_exec(_SessionObject())
    test["ctx"].emit("fs/observed", target("a.txt"), ABSENT, exec_)
    assert await write_intent(test["ctx"], target("a.txt"), exec_) == {"kind": "createIfAbsent"}


@pytest.mark.asyncio
async def test_rejects_an_unread_edit_with_fs_not_observed():
    test = await setup()
    with pytest.raises(FsError) as raised:
        await edit_intent(test["ctx"], target("a.txt"), owner_exec(_SessionObject()))
    assert raised.value.code == "FS_NOT_OBSERVED"


@pytest.mark.asyncio
async def test_rejects_an_edit_with_no_owner_because_it_cannot_prove_prior_observation():
    test = await setup()
    with pytest.raises(FsError) as raised:
        await edit_intent(test["ctx"], target("a.txt"), None)
    assert raised.value.code == "FS_NOT_OBSERVED"


@pytest.mark.asyncio
async def test_rejects_an_edit_whose_actor_has_an_agent_but_no_session():
    test = await setup()
    with pytest.raises(FsError) as raised:
        await edit_intent(test["ctx"], target("a.txt"), SimpleNamespace(agent=SimpleNamespace()))
    assert raised.value.code == "FS_NOT_OBSERVED"


@pytest.mark.asyncio
async def test_returns_the_observed_version_as_the_cas_basis_after_an_observation():
    test = await setup()
    exec_ = owner_exec(_SessionObject())
    test["ctx"].emit("fs/observed", target("a.txt"), present("v3"), exec_)
    assert await edit_intent(test["ctx"], target("a.txt"), exec_) == {"version": "v3"}


@pytest.mark.asyncio
async def test_rejects_editing_a_target_observed_absent_with_fs_not_found():
    test = await setup()
    exec_ = owner_exec(_SessionObject())
    test["ctx"].emit("fs/observed", target("a.txt"), ABSENT, exec_)
    with pytest.raises(FsError) as raised:
        await edit_intent(test["ctx"], target("a.txt"), exec_)
    assert raised.value.code == "FS_NOT_FOUND"


@pytest.mark.asyncio
async def test_a_read_observation_authorizes_an_in_place_write_at_that_version():
    test = await setup()
    exec_ = owner_exec(_SessionObject())
    test["ctx"].emit("fs/observed", target("a.txt"), present("v0"), exec_)  # a read
    assert await write_intent(test["ctx"], target("a.txt"), exec_) == {
        "kind": "replaceIfVersion",
        "version": "v0",
    }


@pytest.mark.asyncio
async def test_a_write_or_edit_observation_refreshes_the_basis_so_the_next_edit_needs_no_reread():
    test = await setup()
    exec_ = owner_exec(_SessionObject())
    # A create records v1; the follow-up edit guards against v1 with no read.
    test["ctx"].emit("fs/observed", target("a.txt"), present("v1"), exec_)
    assert await edit_intent(test["ctx"], target("a.txt"), exec_) == {"version": "v1"}
    # The edit records v2; a second edit guards against v2.
    test["ctx"].emit("fs/observed", target("a.txt"), present("v2"), exec_)
    assert await edit_intent(test["ctx"], target("a.txt"), exec_) == {"version": "v2"}


@pytest.mark.asyncio
async def test_a_no_owner_observation_records_nothing():
    test = await setup()
    test["ctx"].emit("fs/observed", target("a.txt"), present("v0"), None)
    # Still unobserved for any owner.
    with pytest.raises(FsError) as raised:
        await edit_intent(test["ctx"], target("a.txt"), owner_exec(_SessionObject()))
    assert raised.value.code == "FS_NOT_OBSERVED"


@pytest.mark.asyncio
async def test_supports_present_absent_present_transitions_for_one_owner():
    test = await setup()
    ctx = test["ctx"]
    exec_ = owner_exec(_SessionObject())
    a = target("a.txt")
    ctx.emit("fs/observed", a, present("v1"), exec_)
    assert await write_intent(ctx, a, exec_) == {"kind": "replaceIfVersion", "version": "v1"}

    ctx.emit("fs/observed", a, ABSENT, exec_)
    assert await write_intent(ctx, a, exec_) == {"kind": "createIfAbsent"}
    with pytest.raises(FsError) as raised:
        await edit_intent(ctx, a, exec_)
    assert raised.value.code == "FS_NOT_FOUND"

    ctx.emit("fs/observed", a, present("v2"), exec_)
    assert await edit_intent(ctx, a, exec_) == {"version": "v2"}


@pytest.mark.asyncio
async def test_owner_a_observing_does_not_grant_owner_b_edit_authority():
    test = await setup()
    ctx = test["ctx"]
    a = owner_exec(_SessionObject())
    b = owner_exec(_SessionObject())
    ctx.emit("fs/observed", target("a.txt"), present("v0"), a)
    with pytest.raises(FsError) as raised:
        await edit_intent(ctx, target("a.txt"), b)
    assert raised.value.code == "FS_NOT_OBSERVED"
    assert await edit_intent(ctx, target("a.txt"), a) == {"version": "v0"}


@pytest.mark.asyncio
async def test_each_owner_records_its_own_observed_version_independently():
    test = await setup()
    ctx = test["ctx"]
    a = owner_exec(_SessionObject())
    b = owner_exec(_SessionObject())
    ctx.emit("fs/observed", target("a.txt"), present("v0"), a)  # A observed v0
    # B never observed -> createIfAbsent; A still holds v0 -> replaceIfVersion.
    assert await write_intent(ctx, target("a.txt"), b) == {"kind": "createIfAbsent"}
    assert await write_intent(ctx, target("a.txt"), a) == {"kind": "replaceIfVersion", "version": "v0"}


@pytest.mark.asyncio
async def test_fully_decides_the_slot_without_calling_next_so_the_bare_default_is_unreached():
    test = await setup()
    default_ran = []

    def default_thunk() -> None:
        default_ran.append(True)
        return None

    intent = await test["ctx"].waterfall("fs/write-intent", target("a.txt"), owner_exec(_SessionObject()), default_thunk)
    assert intent == {"kind": "createIfAbsent"}
    assert default_ran == []


@pytest.mark.asyncio
async def test_a_second_edit_intent_decider_registered_after_is_not_reached():
    test = await setup()
    ctx = test["ctx"]
    second_ran = []

    def second(*args: Any, **kwargs: Any) -> Any:
        second_ran.append(True)
        return None

    # Registered after fs-observation-policy, so it dispatches second;
    # fs-observation-policy does not call next(), so this never runs.
    ctx.on("fs/edit-intent", second)
    exec_ = owner_exec(_SessionObject())
    ctx.emit("fs/observed", target("a.txt"), present("v0"), exec_)
    assert await edit_intent(ctx, target("a.txt"), exec_) == {"version": "v0"}
    assert second_ran == []


@pytest.mark.asyncio
async def test_a_second_write_intent_decider_registered_after_is_not_reached():
    test = await setup()
    ctx = test["ctx"]
    second_ran = []

    def second(*args: Any, **kwargs: Any) -> Any:
        second_ran.append(True)
        return None

    ctx.on("fs/write-intent", second)
    assert await write_intent(ctx, target("a.txt"), owner_exec(_SessionObject())) == {"kind": "createIfAbsent"}
    assert second_ran == []


@pytest.mark.asyncio
async def test_a_fresh_plugin_after_disposal_starts_with_no_inherited_state():
    ctx = Context()
    exec_ = owner_exec(_SessionObject())
    fiber = await ctx.plugin(FsObservationPolicyPlugin)
    ctx.emit("fs/observed", target("a.txt"), present("v0"), exec_)
    assert await edit_intent(ctx, target("a.txt"), exec_) == {"version": "v0"}
    await fiber.dispose()

    await ctx.plugin(FsObservationPolicyPlugin)
    # Same owner object, but state was released on disposal.
    with pytest.raises(FsError) as raised:
        await edit_intent(ctx, target("a.txt"), exec_)
    assert raised.value.code == "FS_NOT_OBSERVED"


@pytest.mark.asyncio
async def test_no_listeners_remain_after_disposal():
    ctx = Context()
    fiber = await ctx.plugin(FsObservationPolicyPlugin)
    await fiber.dispose()
    # With no listener, the waterfall falls through to the bare default.
    assert await write_intent(ctx, target("a.txt"), owner_exec(_SessionObject())) is None
