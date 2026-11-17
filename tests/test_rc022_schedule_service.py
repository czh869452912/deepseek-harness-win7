import asyncio
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from dsh.cordis import Context
from dsh.core.abort import AbortController
from dsh.schedule.service_current import CurrentScheduleService
from dsh.storage.domain_impl import DomainFacility
from dsh.storage.storage_json import JsonStorageBackend
from dsh.storage.error import StorageError
from dsh.typert.remote import remote_methods
from scripts.rc022_schedule_service_probe import observe


@pytest_asyncio.fixture
async def host(tmp_path):
    ctx=Context();trace=[];agents={}
    for id in ['actor','target']:
        agents[id]=SimpleNamespace(id=id,status='idle',options={},session=SimpleNamespace(id=id,header=SimpleNamespace(delegationDepth=0)),
            inject=lambda message,id=id:trace.append(['inject',id,message]))
    async def flush(session):trace.append(['flush',session.id]);return True
    async def stat(id,options=None):return dict(header=dict(delegationDepth=0))
    async def resolve(id):raise AssertionError('management must not activate a Session')
    ctx.provide('agents',SimpleNamespace(get=agents.get,withoutInitiator=lambda work:work()))
    sessions=SimpleNamespace(flush=flush);persistence=SimpleNamespace(stat=stat)
    ctx.provide('sessions',sessions);ctx.provide('sessionPersistence',persistence)
    ctx.provide('sessionController',SimpleNamespace(resolveAgent=resolve))
    backend=JsonStorageBackend(str(tmp_path/'medium'));ctx.provide('storage',SimpleNamespace(backend=SimpleNamespace(get=lambda name:backend)))
    facility=DomainFacility(ctx,dict(backend='fixture'));ctx.provide('storageDomain',facility)
    fiber=ctx.plugin(CurrentScheduleService,config={});await fiber;service=getattr(ctx.get('schedule'),'cordis.original')
    gates=[]
    try:yield SimpleNamespace(ctx=ctx,service=service,fiber=fiber,facility=facility,backend=backend,agents=agents,sessions=sessions,persistence=persistence,trace=trace,gates=gates)
    finally:
        for gate in gates:gate.set()
        await fiber.dispose();await facility.close_all();await backend.close();await ctx.fiber.dispose()


def request(title='Task'):
    return dict(title=title,prompt='prompt',timing=dict(kind='after',after_seconds=3600),target=dict(kind='session',sessionId='target'))


async def drain(service):
    await asyncio.shield(service.chain);await asyncio.shield(service.notifications)
    if service.runtime.running is not None:await asyncio.shield(service.runtime.running)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_real_management_composition_observations(tmp_path):
    rows=await observe(tmp_path/'files');(tmp_path/'schedule-service-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    by_name={row['step']:row for row in rows};assert len(rows)==28
    assert by_name['final']['activationCalls']==0
    assert by_name['pause']['value']['updatedAt']>by_name['create']['value']['updatedAt']
    assert by_name['conflict']['value']['code']=='schedule_conflict'
    assert by_name['invalid-list']['error']['code']=='schedule/input-invalid'
    assert by_name['refuse-child']['error']['details']==dict(code='subagent_session')
    assert by_name['delete-inactive']['value']==dict(deleted=1) and by_name['delete-inactive-empty']['changes']==0
    assert by_name['observer-committed']['value']['title']=='Observed'


@pytest.mark.asyncio
async def test_remote_contract_exports_current_nine_methods(host):
    exports={entry.get('exportName',entry['method']) for entry in remote_methods(host.service)}
    assert exports=={'deliveryLimits','create','list','catalog','view','history','run','deleteInactive','edit'}


@pytest.mark.asyncio
async def test_notifications_do_not_delay_management_and_close_drains_them(host,monkeypatch):
    entered=asyncio.Event();release=asyncio.Event();flushed=[]
    host.gates.append(release)
    async def held(session):entered.set();await release.wait();flushed.append(session.id);return True
    monkeypatch.setattr(host.sessions,'flush',held)
    created=await asyncio.wait_for(host.service.create(request(),'actor'),2)
    await entered.wait();assert created['status']=='active'
    disposal=asyncio.ensure_future(host.fiber.dispose());await asyncio.sleep(0);await asyncio.sleep(0)
    assert not disposal.done()
    # Teardown may still be draining the timer's accepted transaction.
    for _ in range(30):
        if host.service.stopping:break
        await asyncio.sleep(0)
    assert host.service.stopping
    with pytest.raises(RuntimeError,match='Schedule service is stopping'):await host.service.create(request('late'))
    release.set();await disposal
    assert flushed==['target'] and (await host.service.ready)._closed


@pytest.mark.asyncio
async def test_abandoned_caller_does_not_cancel_accepted_write_or_fifo_edit(host,monkeypatch):
    domain=await host.service.get_domain();entered=asyncio.Event();release=asyncio.Event();id=[];original=domain.unit.put_record
    host.gates.append(release)
    async def held(table,key,value):
        if value['record']['title']=='First':id.append(key);entered.set();await release.wait()
        await original(table,key,value)
    monkeypatch.setattr(domain.unit,'put_record',held)
    first=asyncio.create_task(host.service.create(request('First'),'actor'));await entered.wait()
    second=asyncio.create_task(host.service.edit(dict(id=id[0],action='update',patch=dict(title='Second')),'actor'))
    await asyncio.sleep(0);first.cancel()
    with pytest.raises(asyncio.CancelledError):await first
    assert not second.done();release.set();revised=await second;await drain(host.service)
    assert revised['title']=='Second' and domain.table('tasks').get(id[0])['record']['title']=='Second'
    assert (await host.service.list({}))['total']==1


@pytest.mark.asyncio
async def test_signal_aborted_after_queue_wait_prevents_second_write(host,monkeypatch):
    domain=await host.service.get_domain();entered=asyncio.Event();release=asyncio.Event();original=domain.unit.put_record
    host.gates.append(release)
    async def held(table,key,value):
        if value['record']['title']=='First':entered.set();await release.wait()
        await original(table,key,value)
    monkeypatch.setattr(domain.unit,'put_record',held)
    first=asyncio.create_task(host.service.create(request('First'),'actor'));await entered.wait()
    controller=AbortController();reason=RuntimeError('cancelled while queued')
    second=asyncio.create_task(host.service.create(request('Second'),'actor',controller.signal));await asyncio.sleep(0);await asyncio.sleep(0)
    controller.abort(reason);release.set();await first
    with pytest.raises(RuntimeError) as caught:await second
    assert caught.value is reason
    await drain(host.service);assert [entry['title'] for entry in await host.service.catalog()]==['First']


@pytest.mark.asyncio
async def test_existing_destination_is_revalidated_inside_write_fifo(host,monkeypatch):
    calls=[]
    async def stat(id,options=None):calls.append(id);return dict(header={}) if len(calls)==1 else None
    monkeypatch.setattr(host.persistence,'stat',stat)
    with pytest.raises(Exception) as caught:await host.service.create(dict(request(),target=dict(kind='session',sessionId='stored')))
    assert getattr(caught.value,'code',None)=='invalid_rule' and calls==['stored','stored']
    assert (await host.service.list({}))['total']==0


@pytest.mark.asyncio
async def test_archive_stop_observes_an_earlier_queued_create(host,monkeypatch):
    domain=await host.service.get_domain();entered=asyncio.Event();release=asyncio.Event();original=domain.unit.put_record
    host.gates.append(release)
    async def held(table,key,value):entered.set();await release.wait();await original(table,key,value)
    monkeypatch.setattr(domain.unit,'put_record',held)
    create=asyncio.create_task(host.service.create(request(),'actor'));await entered.wait()
    stop=asyncio.create_task(host.ctx.serial('workspace/session-stop',dict(sessionId='target')));await asyncio.sleep(0)
    assert not stop.done();release.set();await create;await stop;await drain(host.service)
    assert (await host.service.list({}))['total']==0
    activity=await host.ctx.waterfall('workspace/session-activity',dict(sessionId='target'),lambda:[])
    assert activity==[]


@pytest.mark.asyncio
@pytest.mark.parametrize('unknown',[False,True])
async def test_batch_failure_announces_reread_and_unknown_state_quarantines(host,monkeypatch,unknown):
    created=await host.service.create(request(),'actor');await drain(host.service)
    domain=await host.service.get_domain();tasks=domain.table('tasks');await tasks.put(created['id'],dict(tasks.get(created['id']),status='ended'))
    changes=[];host.ctx.on('schedule/changed',lambda:changes.append(True));notices=len(host.trace)
    original=domain.unit.delete_records;failure=StorageError('unknown-state','partial removal') if unknown else OSError('refused')
    async def fail(table,keys):raise failure
    monkeypatch.setattr(domain.unit,'delete_records',fail)
    with pytest.raises(type(failure)) as caught:await host.service.deleteInactive()
    assert caught.value is failure and changes==[True] and len(host.trace)==notices
    if unknown:
        with pytest.raises(StorageError) as caught:await host.service.catalog()
        assert caught.value is failure
    else:
        assert len(await host.service.catalog())==1
        monkeypatch.setattr(domain.unit,'delete_records',original)
        assert await host.service.deleteInactive()==dict(deleted=1)
