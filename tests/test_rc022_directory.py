import asyncio

import pytest

from dsh.core.abort import AbortController
from dsh.session.working_directory import WorkingDirectoryService, WorkingDirectoryError
from scripts.rc022_directory_probe import observe
from scripts.rc022_subagent_fixture import setup


@pytest.mark.asyncio
async def test_actual_directory_fs_agent_projection_and_prompt(tmp_path):
    rows = {row['name']: row for row in await observe(tmp_path)}
    assert len(rows) == 9
    assert rows['initial']['value'] == '<root>'
    assert rows['change']['value'] == '<root>\\child'
    assert rows['independent']['other'] == rows['independent']['original'] == '<root>'
    assert rows['serialized']['values'] == ['<root>\\child\\nested', '<root>\\child']
    assert rows['empty']['error']['code'] == 'WORKING_DIRECTORY_INVALID'
    assert rows['missing']['error']['code'] == 'WORKING_DIRECTORY_NOT_FOUND'
    assert rows['recover']['value'] == '<root>'
    assert rows['context']['value'] == [dict(name='working-directory:current',
        text='Current working directory: "<root>".', interpolate=False)]
    assert len(rows['changes']['notices']) == 4


@pytest.mark.asyncio
async def test_directory_access_rejection_cancellation_and_unload_join(tmp_path):
    (tmp_path/'child').mkdir()
    fixture = await setup(tmp_path/'journal', directory=tmp_path)
    ctx = fixture.ctx
    try:
        agent = (await ctx.agents.create(dict(sessionId='one', meta=dict(cwd=str(tmp_path))))).agent
        entered, release = asyncio.Event(), asyncio.Event()
        async def access(request, next_fn):
            entered.set()
            await release.wait()
            request['signal'].throwIfAborted()
            return await next_fn()
        dispose = ctx.on('working-directory/access', access)
        abort = AbortController()
        operation = asyncio.create_task(ctx.workingDirectory.set(agent, 'child', abort.signal))
        await entered.wait()
        abort.abort()
        release.set()
        with pytest.raises(Exception):
            await operation
        assert ctx.workingDirectory.get(agent.session) == str(tmp_path)
        dispose()
        async def refuse(request, next_fn):
            raise RuntimeError('checkout is retiring')
        dispose = ctx.on('working-directory/access', refuse)
        with pytest.raises(RuntimeError, match='checkout is retiring'):
            await ctx.workingDirectory.set(agent, 'child')
        dispose()
        entered.clear()
        release.clear()
        ctx.on('working-directory/access', access)
        service = ctx.workingDirectory
        operation = asyncio.create_task(service.set(agent, 'child'))
        await entered.wait()
        closing = asyncio.create_task(fixture.directory_provider.dispose())
        await asyncio.wait_for(service.lifecycle.signal.wait_aborted(), 5)
        assert not closing.done()
        release.set()
        with pytest.raises(WorkingDirectoryError) as caught:
            await operation
        assert caught.value.code == 'WORKING_DIRECTORY_UNAVAILABLE'
        await closing
        assert not service.operations
    finally:
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_directory_change_survives_notice_failure_and_replay(tmp_path, monkeypatch):
    (tmp_path/'child').mkdir()
    fixture = await setup(tmp_path/'journal', directory=tmp_path)
    ctx = fixture.ctx
    try:
        agent = (await ctx.agents.create(dict(sessionId='one', meta=dict(cwd=str(tmp_path))))).agent
        monkeypatch.setattr(agent, 'inject', lambda _: (_ for _ in ()).throw(RuntimeError('notice refused')))
        assert await ctx.workingDirectory.set(agent, 'child') == str(tmp_path/'child')
        restored = ctx.sessions.create('restored', dict(meta=dict(cwd=str(tmp_path)), seed=agent.session.snapshotEvents()))
        assert ctx.workingDirectory.get(restored) == str(tmp_path/'child')
        (tmp_path/'child').rmdir()
        # Original directory is also unavailable, and the failed access leaves the state intact.
        monkeypatch.setattr(ctx.fs, 'stat', lambda *_: missing())
        async def missing():
            return None
        with pytest.raises(WorkingDirectoryError) as caught:
            await ctx.workingDirectory.ensure(agent)
        assert caught.value.code == 'WORKING_DIRECTORY_UNAVAILABLE'
        assert ctx.workingDirectory.get(agent.session) == str(tmp_path/'child')
    finally:
        await ctx.fiber.dispose()
