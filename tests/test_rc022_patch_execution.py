from types import SimpleNamespace as NS

import pytest

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.fs.fs_local import FsError, FsTarget
from dsh.fs.fs_observation_policy import CurrentFsObservationPolicy
from dsh.fs.patch_executor import plan_patch, execute_patch
from dsh.fs.tool_fs_sandbox import FsSandboxController
from scripts import rc022_patch_execution_probe as probe


@pytest.mark.asyncio
async def test_real_file_admission_partial_publication_and_observation(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'WORKSPACE', tmp_path)
    rows = {row['name']: row for row in await probe.observe()}
    assert len(rows) == 27 and all(row['providerEmpty'] for row in rows.values())
    assert rows['syntax']['report']['phase'] == 'syntax'
    assert rows['all-four']['files'] == dict(edit='new\r\n', created='new\n', destination='new\n')
    assert rows['repeated-alias']['files'] == dict(a='four\n')
    assert rows['move-chain']['files'] == dict(c='last\n')
    for name in ('independent-refusals', 'blind-overwrite', 'stale', 'missing-source', 'directory', 'mismatch', 'late-binary', 'same-target', 'unread-move-destination'):
        assert rows[name]['report']['phase'] == 'preflight'
        assert rows[name]['observations'] == [] and 'first' not in rows[name]['files']
    assert len(rows['independent-refusals']['report']['refusals']) == 2
    assert rows['unicode-preview']['report']['refusals'][0]['failure']['message'].endswith('🧪'*80+'…')
    for name in ('remove-denied', 'move-remove-denied'):
        row = rows[name]
        assert [item['status'] for item in row['report']['outcomes']] == ['completed', 'failed', 'skipped']
        assert row['files']['source'] == 'old\n' and 'last' not in row['files']
    assert rows['move-remove-denied']['files']['destination'] == 'new\n'
    assert rows['cancel-between']['report']['cancelled']
    assert not rows['cancel-last']['report']['cancelled']
    for name in ('cancel-staged', 'io-published', 'aborted-mutation', 'post-write-stat-failure'):
        assert rows[name]['report']['outcomes'][1]['status'] == 'unknown'
    assert rows['io-unchanged']['report']['outcomes'][1]['status'] == 'failed'
    assert rows['unexpected']['report'] == dict(thrown=dict(code=None, message='defect'))
    assert rows['unexpected']['files']['first'] == 'new\n'


@pytest.mark.asyncio
async def test_plan_preserves_canonical_target_identity_and_orders_resolution_refusals():
    ctx = Context(); signal = AbortController().signal; seen = []
    async def resolve(path, options):
        seen.append(options)
        if path == 'bad': raise FsError('resolution denied', 'FS_PERMISSION_DENIED')
        return FsTarget(target_key='identity', display_path=path)
    ctx.set_service('fs', NS(resolve=resolve))
    execution = NS(signal=signal, agent=None)
    sandbox = FsSandboxController(ctx)
    patch = '*** Begin Patch\n*** Add File: a\n+x\n*** Update File: alias\n*** Move to: other\n@@\n-x\n+y\n*** Delete File: bad\n*** End Patch'
    try:
        plan = await plan_patch(ctx, sandbox, execution, dict(patch=patch))
        assert plan['operations'][0]['target'] is plan['operations'][1]['target']
        assert plan['operations'][1]['destination'] is plan['operations'][0]['target']
        assert plan['operations'][1]['record']['destination'] == 'a'
        assert plan['refusals'][0]['operation']['index'] == 2
        assert all(item == dict(signal=signal) for item in seen)
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_delete_observation_is_owned_by_session_and_unload_releases_decision():
    class Session: pass
    ctx = Context(); fiber = await ctx.plugin(CurrentFsObservationPolicy)
    target = FsTarget(target_key='a', display_path='a')
    session = Session(); actor = NS(agent=NS(session=session))
    async def intent(actor):return await ctx.waterfall('fs/delete-intent', target, actor, lambda: None)
    try:
        with pytest.raises(FsError, match='delete requires reading') as failure: await intent(actor)
        assert failure.value.code == 'FS_NOT_OBSERVED'
        ctx.emit('fs/observed', target, dict(kind='present', version='old'), actor)
        assert await intent(NS(agent=NS(session=session))) == dict(version='old')
        with pytest.raises(FsError):await intent(NS(agent=NS(session=Session())))
        ctx.emit('fs/observed', target, dict(kind='absent'), actor)
        with pytest.raises(FsError, match='cannot delete') as failure: await intent(actor)
        assert failure.value.code == 'FS_NOT_FOUND'
        await fiber.dispose()
        assert await intent(actor) is None
        await ctx.plugin(CurrentFsObservationPolicy)
        with pytest.raises(FsError): await intent(actor)
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_unexpected_resolution_defect_preserves_identity_and_syntax_acquires_nothing():
    ctx = Context(); error = RuntimeError('broken provider'); acquired = []
    async def resolve(*_): acquired.append(True); raise error
    ctx.set_service('fs', NS(resolve=resolve))
    execution = NS(signal=AbortController().signal, agent=None); sandbox = FsSandboxController(ctx)
    try:
        assert (await execute_patch(ctx, sandbox, execution, dict(patch='bad')))['phase'] == 'syntax'
        assert acquired == []
        with pytest.raises(RuntimeError) as failure:
            await execute_patch(ctx, sandbox, execution, dict(patch='*** Begin Patch\n*** Add File: a\n+x\n*** End Patch'))
        assert failure.value is error
    finally: await ctx.fiber.dispose()
