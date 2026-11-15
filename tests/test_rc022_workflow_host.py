import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dsh.core.abort import AbortController
from dsh.workflow.ptc_run import PtcWorkflowRun, agent_info, json_value
from scripts.rc022_workflow_host_probe import observe


@pytest.mark.asyncio
async def test_host_contract_scenarios():
    results={item['name']:item['rows'] for item in await observe()}
    for rows in results.values():
        final=rows[-1]
        assert final['sameDisposal'] and final['pending']==final['children']==0
        assert final['originalMeta']=='host'
    assert results['normal'][-1]['result']['value']==7
    assert results['late-child'][-1]['disposed']==['child']
    assert results['late-child'][-1]['result']['agentsStarted']==1
    assert results['cancel-wait'][-1]['result']['stopReason']=='cancelled'
    assert results['dispose-failure'][-1]['warningCount']==1
    assert results['fixed-cwd'][-1]['calls'][-1]['cwd']=='C:/initial'
    assert results['validation'][-1]['calls']==['cwd',dict(cwd='C:/initial',timeout=None,policy=dict(mode='read-only'),global_='workflowHost')]
    assert [row for row in results['open-progress'] if row.get('event')=='end'][0]['value']['outcome']=='cancelled'


@pytest.mark.asyncio
async def test_cwd_capture_and_disposal_waiters_do_not_steal_ownership():
    held=asyncio.get_event_loop().create_future();entered=asyncio.Event();release=asyncio.Event();external=AbortController();calls=[]
    async def ensure(parent,signal):return await held
    async def execute(spec):
        calls.append(spec);entered.set();await release.wait()
        return dict(value=dict(value=None,stopReason='completed',agentsStarted=0))
    runtime=SimpleNamespace(sandboxMode='read-only',programFormat='script',resolve=lambda value:value,run=execute)
    ctx=SimpleNamespace(get=lambda _:SimpleNamespace(ensure=ensure))
    run=PtcWorkflowRun(ctx,None,runtime,'run',dict(name='n'),None,{},'stub',dict(mode='read-only'),None,external.signal)
    await asyncio.sleep(0);assert not calls
    held.set_result('C:/chosen');await entered.wait()
    disposal=run.dispose()
    async def wait():await disposal
    waiter=asyncio.create_task(wait());await asyncio.sleep(0);waiter.cancel()
    with pytest.raises(asyncio.CancelledError):await waiter
    assert not run.result.cancelled() and not disposal.task.cancelled()
    release.set();await disposal
    assert (await run.result)['stopReason']=='cancelled'
    assert not external.signal._listeners
    assert calls[0]['program'].startswith('(async () => {\n')


@pytest.mark.parametrize('value',[float('nan'),float('inf'),True,0,-1,9007199254740992])
def test_invalid_agent_sequence(value):
    with pytest.raises(ValueError,match='positive integer'):
        agent_info(dict(seq=value,label='x',childId='x'))


def test_invalid_and_detached_binding_json():
    for value in [object(),float('nan'),dict(value=object())]:
        with pytest.raises(ValueError,match='lossless JSON'):json_value(value)
    source=dict(child=[1]);snapshot=json_value(source);snapshot['child'].append(2)
    assert source==dict(child=[1])


def test_original_guest_identity():
    root=Path(__file__).resolve().parents[1]
    receipt=json.loads((root/'dsh/workflow/ptc_guest.provenance.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((root/receipt['output']).read_bytes()).hexdigest()==receipt['sha256']
