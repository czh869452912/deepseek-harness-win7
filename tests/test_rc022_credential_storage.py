import asyncio
import json
from pathlib import Path

import pytest

from dsh.cordis.context import Context
from dsh.credentials import local_current as module
from dsh.credentials.local_current import CurrentCredentialsLocalPlugin
from scripts.rc022_credential_storage_probe import observe


async def mounted(tmp_path, **options):
    ctx = Context()
    await ctx.plugin(CurrentCredentialsLocalPlugin, dict(path=str(tmp_path/'credentials.yaml'), watch=False, **options))
    return ctx, ctx.credentials


@pytest.mark.asyncio
async def test_actual_document_operations_and_disposal_corpus(tmp_path):
    rows = await observe(tmp_path/'files')
    (tmp_path/'credential-storage-observations.json').write_text(json.dumps(rows), encoding='utf-8')
    assert len(rows) == 29
    assert rows[0]['states'][0]['exists'] is False
    assert rows[0]['states'][1]['ref'] == {'value': 'new', 'source': 'file'}
    assert rows[0]['states'][-1]['ref'] is None
    assert rows[-2]['drainPending'] and rows[-2]['sameObject']
    assert 'before the queued' in rows[-2]['queuedError']
    assert rows[-1]['watch'][-1] == dict(event='KEY', value=None)


@pytest.mark.asyncio
async def test_failed_atomic_commit_keeps_cache_and_disk_then_queue_recovers(tmp_path, monkeypatch):
    ctx, service = await mounted(tmp_path)
    try:
        await service.set('KEY', 'before')
        before = Path(service.filepath).read_bytes()
        original = module.write_file_atomic
        async def failed(*args, **kwargs): raise OSError('injected disk failure')
        monkeypatch.setattr(module, 'write_file_atomic', failed)
        with pytest.raises(OSError): await service.set('KEY', 'failed')
        assert service.resolve('KEY').value == 'before'
        assert Path(service.filepath).read_bytes() == before
        monkeypatch.setattr(module, 'write_file_atomic', original)
        await service.set('KEY', 'after')
        assert service.resolve('KEY').value == 'after'
        assert not list(tmp_path.glob('*.lock')) and not list(tmp_path.glob('*.tmp'))
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_abandoned_waiter_does_not_cancel_durable_operation(tmp_path):
    ctx, service = await mounted(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    async def mutate(current):
        entered.set(); await release.wait(); return dict(kind='grant', payload='committed')
    task = service.modifyRecord('owner/a', mutate)
    await entered.wait(); task.cancel(); release.set()
    await service.set('KEY', 'queued')
    assert service.readRecord('owner/a')['payload'] == 'committed'
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_two_mounted_writers_reconcile_under_document_lock(tmp_path):
    first, a = await mounted(tmp_path)
    second, b = await mounted(tmp_path)
    try:
        await asyncio.gather(a.set('FIRST', 'a'), b.set('SECOND', 'b'))
        await a.queue_refresh(); await b.queue_refresh()
        assert a.resolve('FIRST').value == b.resolve('FIRST').value == 'a'
        assert a.resolve('SECOND').value == b.resolve('SECOND').value == 'b'
    finally: await first.fiber.dispose(); await second.fiber.dispose()


@pytest.mark.asyncio
async def test_live_watcher_reload_failure_recovery_removal_and_disposal(tmp_path):
    ctx = Context(); events = asyncio.Queue()
    ctx.on('credentials/reference-updated', lambda key: events.put_nowait(key))
    await ctx.plugin(CurrentCredentialsLocalPlugin, dict(path=str(tmp_path/'credentials.yaml'), debounceMs=5))
    service = ctx.credentials; watcher = service._watcher
    try:
        filename = Path(service.filepath)
        filename.write_bytes(b'version: 1\nrefs: {KEY: external}\n'); filename.chmod(0o600)
        assert await asyncio.wait_for(events.get(), 2) == 'KEY'
        assert service.resolve('KEY').value == 'external'
        filename.write_bytes(b'version: 2\nrefs: {KEY: invalid}\n')
        # Queue refresh is the same serialized operation the watcher admits.
        await service.queue_refresh()
        assert service.resolve('KEY').value == 'external'
        filename.write_bytes(b'version: 1\nrefs: {KEY: recovered}\n')
        assert await asyncio.wait_for(events.get(), 2) == 'KEY'
        assert service.resolve('KEY').value == 'recovered'
        filename.unlink()
        assert await asyncio.wait_for(events.get(), 2) == 'KEY'
        assert service.resolve('KEY') is None
    finally: await ctx.fiber.dispose()
    assert watcher.done() and service._tail.done()
    assert not filename.exists()


@pytest.mark.asyncio
async def test_browser_signing_secret_waits_for_commit_and_survives_restart(tmp_path):
    from dsh.host.connection.auth_current import CurrentBrowserAuth
    ctx, service = await mounted(tmp_path)
    first = await CurrentBrowserAuth.create(ctx.root, service, 30)
    await ctx.fiber.dispose()
    ctx, service = await mounted(tmp_path)
    try:
        second = await CurrentBrowserAuth.create(ctx.root, service, 30)
        assert first.secret == second.secret
    finally: await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_canonical_web_profile_activates_current_storage_and_restarts(tmp_path):
    from canonical_web_fixture import web_context, close_web_context
    from dsh.credentials.local_current import CurrentLocalCredentialProvider
    ctx = await web_context(tmp_path)
    try:
        assert isinstance(ctx.credentials, CurrentLocalCredentialProvider)
        await ctx.credentials.set('CURRENT_FIXTURE', 'persisted')
        assert ctx.get('connection') is not None
    finally: await close_web_context(ctx)
    ctx = await web_context(tmp_path)
    try:
        assert ctx.credentials.resolve('CURRENT_FIXTURE').value == 'persisted'
    finally: await close_web_context(ctx)
