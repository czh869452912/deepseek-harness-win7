import asyncio
from types import SimpleNamespace

import pytest

from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.scope import create_scope, ScopeKey
from dsh.skill.registry import SkillRegistry


def definition(name="sample", content="instructions", **kwargs):
    return dict(name=name, description="description", content=content, source="test", **kwargs)


@pytest.mark.asyncio
async def test_scope_shadow_and_exact_effect_withdrawal():
    ctx = Context()
    await ctx.plugin(SkillRegistry)
    skills = ctx.get("skills")
    scope = ScopeKey("private")
    child = create_scope(ctx, scope).ctx
    try:
        skills.register(definition())
        dispose = child.get("skills").register(definition(content="private"))
        duplicate = child.get("skills").register(definition(content="loser"))
        duplicate()
        assert (await skills.get("sample"))["content"] == "instructions"
        assert (await skills.get("sample", {"scope": scope}))["content"] == "private"
        dispose()
        assert (await skills.get("sample", {"scope": scope}))["content"] == "instructions"
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_provider_incomplete_cache_invalidation_and_load_locator():
    ctx = Context()
    await ctx.plugin(SkillRegistry)
    skills = ctx.get("skills")
    calls, controls, complete = [], [], [False]
    opaque = object()
    async def discover(options):
        calls.append(options.get("cwd"))
        return {"candidates": [dict(definition(provider="remote"), rank=10, locator=opaque)], "complete": complete[0]}
    async def get(candidate, options):
        assert candidate["locator"] is opaque
        return definition(provider="remote")
    def factory(control):
        controls.append(control)
        return SimpleNamespace(name="remote", list=discover, get=get)
    dispose = skills.register_provider(factory)
    try:
        assert not (await skills.snapshot())["complete"]
        complete[0] = True
        assert (await skills.snapshot())["complete"]
        assert (await skills.get("sample"))["provider"] == "remote"
        assert len(calls) == 2
        controls[0].invalidate()
        await skills.list()
        assert len(calls) == 3
        dispose()
        assert controls[0].signal.aborted and await skills.list() == []
        revision = skills.revision
        controls[0].invalidate()
        assert skills.revision == revision
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancellation_does_not_cancel_borrowed_provider_and_failed_registration_aborts():
    ctx = Context()
    await ctx.plugin(SkillRegistry)
    skills = ctx.get("skills")
    future = asyncio.get_running_loop().create_future()
    controls = []
    def create(control):
        controls.append(control)
        return SimpleNamespace(name="slow", list=lambda _: future, get=lambda *_: None)
    skills.register_provider(create)
    try:
        with pytest.raises(ValueError, match="already registered"):
            skills.register_provider(create)
        assert controls[1].signal.aborted and not controls[0].signal.aborted
        abort = AbortController()
        task = asyncio.create_task(skills.snapshot({"signal": abort.signal}))
        await asyncio.sleep(0)
        abort.abort()
        with pytest.raises(RuntimeError, match="aborted"):
            await asyncio.wait_for(task, 1)
        assert not future.cancelled()
        future.set_result([])
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unstable_revision_retries_once_then_reports_incomplete():
    ctx = Context()
    await ctx.plugin(SkillRegistry)
    skills = ctx.get("skills")
    calls = []
    def create(control):
        async def discover(options):
            calls.append(True)
            control.invalidate()
            return []
        return SimpleNamespace(name="changing", list=discover, get=lambda *_: None)
    skills.register_provider(create)
    try:
        assert await skills.snapshot() == {"skills": [], "complete": False}
        assert len(calls) == 2 and not skills.cache
    finally:
        await ctx.fiber.dispose()
