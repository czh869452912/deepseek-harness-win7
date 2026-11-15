import asyncio
from types import SimpleNamespace as NS

import pytest

from dsh.api.session_catalogs_authorized import AuthorizedSessionSkillCatalog
from dsh.cordis import Context
from dsh.core.abort import NEVER_ABORTED, AbortController
from dsh.typert.current import CurrentTypertRegistry


@pytest.mark.asyncio
async def test_actual_directory_persistence_and_retained_preset_catalog(tmp_path):
    from scripts.rc022_skill_catalog_probe import observe
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert rows['cold-projected']['agents'] == rows['persisted-directory']['agents'] == 0
    assert rows['cold-projected']['call'] == dict(cwd='moved', scope='standing')
    assert rows['live-directory']['call'] == dict(cwd='moved', scope='live')
    skills = rows['cold-projected']['value']['skills']
    assert [row['name'] for row in skills] == ['global', 'review']
    assert skills[1]['path'] == '/virtual/SKILL.md' and not skills[1]['modelInvocable']
    assert rows['retained-during-read']['generations'] == ['coding', 'coding']
    assert rows['released-after-read']['generations'] == ['coding']
    assert rows['retired-view']['value']['skills'][1]['name'] == 'review'
    assert rows['replacement-view']['value']['skills'][1]['name'] == 'review-new'
    assert rows['released-after-error']['generations'] == []
    assert rows['missing']['code'] == 'session/not-found'


async def controlled(values=None, cwd=None, live=None, ensure=None):
    ctx = Context(); await ctx.plugin(CurrentTypertRegistry); disposed = []
    observation = NS(header=NS(cwd=cwd), projections=dict(values=values or {}), dispose=lambda: disposed.append(True))
    async def observe(*args):
        assert args == ('sample',)
        return observation
    ctx.set_service('sessionQuery', NS(observeSession=observe))
    ctx.set_service('agents', NS(get=lambda _: live))
    ctx.set_service('workingDirectory', NS(defaultDirectory='/default', ensure=ensure))
    return ctx, AuthorizedSessionSkillCatalog(ctx), observation, disposed


@pytest.mark.asyncio
async def test_live_ensure_holds_observation_and_rechecks_agent_after_await():
    live = NS(); entered, gate = asyncio.Event(), asyncio.Event(); current = [live]; calls = []
    async def ensure(agent, signal):
        assert agent is live and signal is NEVER_ABORTED and not disposed
        entered.set(); await gate.wait(); assert not disposed
        return '/ensured'
    ctx, catalog, _, disposed = await controlled(live=live, ensure=ensure)
    ctx.set_service('agents', NS(get=lambda _: current[0]))
    async def listing(options): calls.append(options); return []
    ctx.set_service('skills', NS(list=listing))
    async def acquire(preset): calls.append(preset); return NS(key='retained', dispose=dispose)
    async def dispose(): calls.append('released')
    ctx.set_service('agentPresets', NS(acquireScope=acquire, serviceFor=lambda *_: pytest.fail('Agent disappeared')))
    pending = asyncio.ensure_future(catalog.list(dict(sessionId='sample'), NEVER_ABORTED))
    try:
        await entered.wait(); current[0] = None; gate.set()
        assert await pending == dict(skills=[])
        assert disposed == [True] and calls == [None, dict(cwd='/ensured', scope='retained'), 'released']
    finally:
        gate.set(); await asyncio.gather(pending, return_exceptions=True); await ctx.fiber.dispose()


@pytest.mark.parametrize('failure', ['ensure', 'projection', 'registry', 'acquire', 'list', 'dispose'])
@pytest.mark.asyncio
async def test_failures_release_exact_owners_without_wrapping_disposal(failure):
    calls = []; original = RuntimeError('original disposal')
    async def ensure(*_): raise RuntimeError('ensure failed')
    ctx, catalog, observation, disposed = await controlled(live=NS() if failure=='ensure' else None, ensure=ensure)
    async def release():
        calls.append('released')
        if failure=='dispose': raise original
    async def acquire(_):
        if failure=='acquire': raise RuntimeError('unknown preset')
        calls.append('acquired'); return NS(key='scope', dispose=release)
    async def listing(options):
        calls.append(options)
        if failure=='list': raise RuntimeError('list failed')
        return []
    ctx.set_service('agentPresets', NS(acquireScope=acquire, serviceFor=lambda *_: None))
    if failure!='registry': ctx.set_service('skills', NS(list=listing))
    if failure=='projection': observation.projections = None
    try:
        if failure=='acquire':
            assert await catalog.list(dict(sessionId='sample'), NEVER_ABORTED) == dict(skills=[])
            assert calls == [dict(cwd='/default', scope=None)]
        else:
            with pytest.raises(Exception) as caught: await catalog.list(dict(sessionId='sample'), NEVER_ABORTED)
            if failure=='dispose': assert caught.value is original
            else: assert caught.value.code == 'gateway/internal'
            if failure in ('list','dispose'): assert calls[-1] == 'released'
            else: assert not calls
        assert disposed == [True]
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_live_cancel_is_inspection_failure_and_releases_observation():
    abort = AbortController(); abort.abort()
    async def ensure(_, signal): signal.throwIfAborted()
    ctx, catalog, _, disposed = await controlled(live=NS(), ensure=ensure)
    try:
        with pytest.raises(Exception) as caught: await catalog.list(dict(sessionId='sample'), abort.signal)
        assert caught.value.code == 'gateway/internal' and disposed == [True]
    finally: await ctx.fiber.dispose()
