import asyncio
import json

import pytest

from dsh.cordis.context import Context
from dsh.storage.domain_error import DomainError
from dsh.storage.domain_spec import define_domain, domain_table
from dsh.storage.error import StorageError
from dsh.storage.hub import StoragePlugin
from dsh.storage.plugins import StorageDomainPlugin, StorageJsonPlugin


async def storage_context(root):
    ctx = Context()
    await ctx.plugin(StoragePlugin)
    await ctx.plugin(StorageJsonPlugin, config={'root': str(root)})
    domain_fiber = ctx.plugin(StorageDomainPlugin, config={'backend': 'json'})
    await domain_fiber
    return ctx, domain_fiber


def domain_spec(name):
    return define_domain(name=name, version=1, tables={'items': domain_table(lambda value: value)})


def delay_write(monkeypatch, domain):
    entered, release = asyncio.Event(), asyncio.Event()
    put_record = domain.unit.put_record

    async def put(table, key, value):
        entered.set()
        await release.wait()
        await put_record(table, key, value)

    monkeypatch.setattr(domain.unit, 'put_record', put)
    return entered, release


@pytest.mark.asyncio
async def test_close_rejects_new_writes_immediately_and_shares_release(tmp_path, monkeypatch):
    ctx, _ = await storage_context(tmp_path)
    facility = ctx.get('storageDomain')
    spec = domain_spec('shared_close')
    domain = await facility.open(spec)
    table = domain.table('items')
    entered, release = delay_write(monkeypatch, domain)
    close_calls = []
    close_unit = domain.unit.close

    async def close():
        close_calls.append('release')
        await close_unit()

    monkeypatch.setattr(domain.unit, 'close', close)
    write = asyncio.create_task(table.put('saved', {'value': 1}))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        first, second = domain.close(), domain.close()
        assert not first.done() and not second.done()
        assert table.get('saved') is None
        with pytest.raises(DomainError) as error:
            await table.put('late', 2)
        assert error.value.code == 'closed'
        with pytest.raises(DomainError) as error:
            await facility.open(spec)
        assert error.value.code == 'already-open'
        release.set()
        await asyncio.gather(write, first, second)
        await domain.close()
        assert close_calls == ['release']
        with pytest.raises(DomainError) as error:
            table.get('saved')
        assert error.value.code == 'closed'
        reopened = await facility.open(spec)
        assert reopened.table('items').get('saved') == {'value': 1}
        assert reopened.table('items').get('late') is None
    finally:
        release.set()
        await write
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancelled_close_waiter_does_not_cancel_durable_drain(tmp_path, monkeypatch):
    ctx, _ = await storage_context(tmp_path)
    domain = await ctx.get('storageDomain').open(domain_spec('cancel_close'))
    entered, release = delay_write(monkeypatch, domain)
    write = asyncio.create_task(domain.table('items').put('saved', 3))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        cancelled, survivor = domain.close(), domain.close()
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert not survivor.done()
        release.set()
        await asyncio.gather(write, survivor)
        assert json.loads((tmp_path / 'cancel_close.json').read_text(encoding='utf-8'))['tables']['items'] == {'saved': 3}
    finally:
        release.set()
        await write
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_close_all_stops_every_domain_before_waiting_for_first(tmp_path, monkeypatch):
    ctx, _ = await storage_context(tmp_path)
    facility = ctx.get('storageDomain')
    first = await facility.open(domain_spec('first_close'))
    second = await facility.open(domain_spec('second_close'))
    entered, release = delay_write(monkeypatch, first)
    second_closing = asyncio.Event()
    second_close = second.unit.close

    async def close_second():
        second_closing.set()
        await second_close()

    monkeypatch.setattr(second.unit, 'close', close_second)
    write = asyncio.create_task(first.table('items').put('saved', 4))
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        closing = asyncio.create_task(facility.close_all())
        await asyncio.wait_for(second_closing.wait(), 2)
        assert not closing.done()
        with pytest.raises(DomainError) as error:
            await second.table('items').put('late', 5)
        assert error.value.code == 'closed'
        release.set()
        await asyncio.gather(write, closing)
    finally:
        release.set()
        await write
        if closing is not None:
            await closing
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_domain_unload_keeps_hub_mounted_for_draining_change_events(tmp_path, monkeypatch):
    ctx, domain_fiber = await storage_context(tmp_path)
    storage = ctx.get('storage')
    facility = storage.domain
    domain = await facility.open(domain_spec('unload_close'))
    entered, release = delay_write(monkeypatch, domain)
    observed = []

    def changed(change):
        mounted = storage.domain
        observed.append((mounted is facility, mounted.get(change.domain).table(change.table).get(change.key)))

    ctx.on('domain/changed', changed)
    write = asyncio.create_task(domain.table('items').put('saved', {'value': 6}))
    unloading = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        unloading = asyncio.ensure_future(domain_fiber.dispose())
        # Calling close starts the same drain that the plugin disposer joins.
        draining = domain.close()
        assert storage.domain is facility
        release.set()
        await asyncio.gather(write, draining, unloading)
        assert observed == [(True, {'value': 6})]
        with pytest.raises(StorageError) as error:
            storage.form('domain')
        assert error.value.code == 'form-not-mounted'
        persisted = json.loads((tmp_path / 'unload_close.json').read_text(encoding='utf-8'))
        assert persisted['tables']['items'] == {'saved': {'value': 6}}
    finally:
        release.set()
        await write
        if unloading is not None:
            await unloading
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_release_is_shared_and_does_not_free_domain_name(tmp_path, monkeypatch):
    ctx, _ = await storage_context(tmp_path)
    facility = ctx.get('storageDomain')
    spec = domain_spec('failed_close')
    domain = await facility.open(spec)
    close_calls = []
    failure = OSError('release fixture failed')
    close_unit = domain.unit.close

    async def close():
        close_calls.append('release')
        raise failure

    monkeypatch.setattr(domain.unit, 'close', close)
    try:
        results = await asyncio.gather(domain.close(), domain.close(), return_exceptions=True)
        assert results == [failure, failure]
        with pytest.raises(OSError) as error:
            await domain.close()
        assert error.value is failure
        assert close_calls == ['release']
        with pytest.raises(DomainError) as error:
            await facility.open(spec)
        assert error.value.code == 'already-open'
    finally:
        await close_unit()
        # The failed close remains failed; root disposal observes that failure.
        await ctx.fiber.dispose()
