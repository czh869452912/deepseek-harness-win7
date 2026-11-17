import asyncio
import json
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.schedule.runtime_current import CurrentScheduleRuntime
from scripts.rc022_schedule_runtime_probe import observe


@pytest.mark.asyncio
async def test_current_runtime_receipts_recovery_and_targets(tmp_path):
    rows=await observe();(tmp_path/'schedule-runtime-observations.json').write_text(json.dumps(rows),encoding='utf-8')
    by_name={row['case']:row for row in rows};assert len(rows)==26
    assert by_name['one']['tasks'][0]['status']=='ended'
    batch=by_name['batch'];assert len([call for call in batch['trace'] if call[0]=='followup'])==1
    assert batch['tasks'][0]['lastDelivery']['messageId']==batch['tasks'][1]['lastDelivery']['messageId']
    partial=by_name['partialCommit'];assert partial['executing']==['a'] and 'lastDelivery' not in partial['tasks'][1]
    for name in ['flushFalse','flushReject','activateReject']:
        assert 'lastDelivery' not in by_name[name]['tasks'][0] and by_name[name]['warnings']==1 and by_name[name]['timer'] is None
    retry=by_name['newRetry'];assert len([call for call in retry['trace'] if call[0]=='create'])==1
    assert len([call for call in retry['trace'] if call[0]=='followup'])==2
    assert 'pendingDelivery' not in retry['tasks'][0]
    assert by_name['recoveryIdle']['executing']==['a'] and not any(call[0]=='commit' for call in by_name['recoveryIdle']['trace'])
    assert by_name['manual']['outcome']['value'][1]['admitted'] is False
    assert by_name['manualPaused']['tasks'][0]['status']=='paused'
    assert by_name['farFuture']['timer']==2147483647


def context(agents=None):
    warnings=[];services={'agents':agents or SimpleNamespace(withoutInitiator=lambda operation:operation())}
    return SimpleNamespace(get=services.get,logger=SimpleNamespace(warn=warnings.append)),warnings


@pytest.mark.asyncio
async def test_drive_coalesces_requests_and_dispose_drains_accepted_transaction():
    ctx,warnings=context();entered=asyncio.Event();release=asyncio.Event();calls=[]
    async def transact(work):
        calls.append('enter');entered.set();await release.wait();await work();calls.append('leave')
    timer=CurrentScheduleRuntime(ctx,lambda:[],transact,None,None,{},None)
    timer.requestDrive();await entered.wait();running=timer.running
    timer.requestDrive();timer.requestDrive();assert timer.running is running
    disposal=asyncio.create_task(timer.dispose());await asyncio.sleep(0)
    assert not disposal.done() and timer.stopping
    release.set();await disposal
    timer.requestDrive();assert calls==['enter','leave'] and timer.timer is None and not warnings


@pytest.mark.asyncio
async def test_request_arriving_during_drive_gets_one_following_fifo_slot():
    ctx,warnings=context();entered=asyncio.Event();release=asyncio.Event();calls=[]
    async def transact(work):
        calls.append('enter')
        if len(calls)==1:entered.set();await release.wait()
        await work()
    timer=CurrentScheduleRuntime(ctx,lambda:[],transact,None,None,{},None)
    timer.requestDrive();await entered.wait();timer.requestDrive();timer.requestDrive();release.set()
    await asyncio.shield(timer.running);await asyncio.sleep(0)
    assert calls==['enter','enter'] and not warnings
    await timer.dispose()


@pytest.mark.asyncio
async def test_initiator_shutdown_refuses_admission_without_leaking_coroutine():
    def refuse(operation):raise RuntimeError('agent initiator scope is disposed')
    ctx,warnings=context(SimpleNamespace(withoutInitiator=refuse))
    timer=CurrentScheduleRuntime(ctx,lambda:[],None,None,None,{},None)
    timer.requestDrive()
    assert timer.running is None and timer.requested is False and len(warnings)==1
    await timer.dispose()


@pytest.mark.asyncio
async def test_manual_abort_checked_after_fifo_admission_before_target_activation():
    ctx,warnings=context();entered=asyncio.Event();release=asyncio.Event();reads=[]
    async def transact(work):entered.set();await release.wait();return await work()
    def tasks():reads.append(True);return []
    timer=CurrentScheduleRuntime(ctx,tasks,transact,None,None,{},None)
    controller=AbortController();reason=RuntimeError('cancelled at queue')
    request=asyncio.create_task(timer.runNow('id',controller.signal));await entered.wait();controller.abort(reason);release.set()
    with pytest.raises(RuntimeError) as caught:await request
    assert caught.value is reason and not reads and not warnings
    await timer.dispose()
