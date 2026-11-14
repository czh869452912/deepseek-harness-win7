import asyncio

import pytest

from scripts.rc022_hmr_watch_probe import observe


@pytest.mark.asyncio
async def test_profile_self_replacement_can_exit_without_a_final_barrier(tmp_path, monkeypatch):
    from dsh.cordis.context import Context
    roots = {}
    original = Context.__init__
    def initialized(self, *args, **kwargs):
        original(self, *args, **kwargs)
        roots[id(self.root)] = self.root
    monkeypatch.setattr(Context, '__init__', initialized)
    rows = await asyncio.wait_for(observe(tmp_path/'immediate-exit', settle_before_exit=False), 15)
    assert rows[-2] == dict(step='provider-replacement', old_active=False, value='after-hmr-replacement')
    assert rows[-1] == dict(mode='cancel', before='initial', value=None, active=False)
    for ctx in roots.values():
        if ctx.root is not ctx:
            continue
        await asyncio.wait_for(ctx.fiber.await_settled(), 2)
        assert ctx.get('hmr') is None
        assert ctx.get('loader') is None
        assert ctx.fiber.settlement_tasks() == []


@pytest.mark.asyncio
async def test_shutdown_releases_admission_but_still_awaits_real_resource_cleanup():
    from dsh.boot.recomposition import _await_loader
    from dsh.cordis.context import Context
    from dsh.cordis.loader import Loader
    ctx = Context()
    await ctx.plugin(Loader)
    cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
    async def cleanup():
        cleanup_started.set()
        await cleanup_release.wait()
    def resource(owner):
        owner.effect(lambda: cleanup)
    await ctx.plugin(resource)
    admission_started, admission_release = asyncio.Event(), asyncio.Event()
    loader = ctx.loader
    original = loader.await_
    async def delayed():
        admission_started.set()
        await admission_release.wait()
        await original()
    loader.await_ = delayed
    closing = None
    try:
        admission = asyncio.create_task(_await_loader(ctx))
        await admission_started.wait()
        closing = asyncio.ensure_future(ctx.fiber.dispose())
        await asyncio.wait_for(admission, 2)
        await cleanup_started.wait()
        assert not closing.done()
        admission_release.set()
        cleanup_release.set()
        await asyncio.wait_for(closing, 2)
        await asyncio.wait_for(ctx.fiber.await_settled(), 2)
        assert ctx.fiber.settlement_tasks() == []
    finally:
        admission_release.set()
        cleanup_release.set()
        if closing is not None:
            await closing
        await ctx.fiber.dispose()
