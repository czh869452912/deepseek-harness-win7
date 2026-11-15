import asyncio
from types import SimpleNamespace as NS
import pytest
from scripts.rc022_external_settlement_probe import observe


@pytest.mark.asyncio
async def test_external_settlement_cancellation_diagnostics_and_memoized_cleanup():
    rows=await observe()
    assert len(rows)==41
    results=[row for row in rows if row['kind']=='result']
    assert all(row['removed']==['abort'] for row in results)
    assert results[0]['value']['stopReason']=='completed'
    assert results[8]['value']==dict(output=[dict(type='text',text='partial')],stopReason='aborted')
    assert results[16]['value']['stopReason']=='error'
    assert results[24]['reports']==[]
    for row in results:
        diagnostic=row['value'].get('diagnostic')
        if diagnostic is not None:
            assert len(diagnostic.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace').encode('utf-8'))<=4096
    assert all(row['same'] and row['errorIdentity'] and row['before']==['cancel','teardown'] for row in rows if row['kind']=='dispose')
    from dsh.subagent.out_of_process import subprocess_run_handle
    from dsh.core.abort import AbortController
    shared=asyncio.get_running_loop().create_future()
    handle=subprocess_run_handle(dict(id='future',result=shared,signal=AbortController().signal,onAbort=lambda *_:None,
        requestCancel=lambda:None,teardown=lambda:shared))
    assert handle.dispose() is shared and handle.dispose() is shared
    shared.set_result(None)


@pytest.mark.asyncio
async def test_shared_settlement_composes_with_actual_external_activation_owner(tmp_path):
    from scripts.rc022_subagent_fixture import setup
    from dsh.subagent.out_of_process import NO_START_CAPABILITIES,settle_run_result,subprocess_run_handle
    fixture=await setup(tmp_path);ctx=fixture.ctx;entered=asyncio.Event();release=asyncio.Event();trace=[]
    try:
        parent=(await ctx.agents.create(dict(sessionId='parent',agentOptions=dict(provider='script',model='model')))).agent
        async def start(request):
            cancelled=False;done=asyncio.Event();signal=request['signal']
            def cancel(*_):
                nonlocal cancelled
                cancelled=True;done.set()
            signal.addEventListener('abort',cancel)
            async def attempt():await done.wait();return dict(output=[],stopReason='completed')
            async def teardown():trace.append('teardown');entered.set();await release.wait();trace.append('exited')
            result=settle_run_result(dict(attempt=attempt,collectOutput=lambda:[],cancelled=lambda:cancelled,signal=signal,onAbort=cancel))
            return subprocess_run_handle(dict(id='external',result=result,signal=signal,onAbort=cancel,requestCancel=cancel,teardown=teardown))
        fixture.service.registerProvider(NS(name='external',capabilities=NO_START_CAPABILITIES,inheritsParentContext=False,start=start))
        receipt=await fixture.service.startActivation(dict(provider='external',parent=parent,prompt=[dict(type='text',text='task')],label='Task',signal=fixture.signal,delivery='caller'))
        fixture.service.interrupt(receipt['childId'],dict(kind='user'))
        await entered.wait()
        assert not receipt['result'].done() or (await receipt['result'])['stopReason']=='aborted'
        first=receipt['dispose']();second=receipt['dispose']()
        assert trace==['teardown']
        release.set();await asyncio.gather(first,second)
        assert (await receipt['result'])['stopReason']=='aborted' and trace==['teardown','exited']
        assert fixture.service.manager.resident=={}
    finally:
        release.set();await ctx.fiber.dispose()
