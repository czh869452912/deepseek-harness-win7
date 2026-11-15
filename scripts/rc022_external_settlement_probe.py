"""Pair external result and memoized teardown contracts without a fake OS claim."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(fails=fails,cancelled=cancelled,sinkThrows=sink,diagnostic=diagnostic) for fails in (False,True) for cancelled in (False,True)
        for sink in (False,True) for diagnostic in (None,'safe diagnostic','文😀'*1200,'\ud800'*1500)]


async def observe():
    from dsh.subagent.out_of_process import settle_run_result,subprocess_run_handle,assert_positive_finite
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    rows=[]
    for case in cases():
        signal=AbortController().signal;removed=[];reports=[];original=signal.removeEventListener
        def remove(*args):removed.append(args[0]);original(*args)
        tracked=NS(removeEventListener=remove)
        def on_abort(*args):pass
        signal.addEventListener('abort',on_abort)
        async def attempt():
            await asyncio.sleep(0)
            if case['fails']:raise RuntimeError('private failure')
            result=dict(output=[dict(type='text',text='finished')],stopReason='completed')
            if case['diagnostic'] is not None:result['diagnostic']=case['diagnostic']
            return result
        def report(error,reason):
            reports.append([str(error),reason])
            if case['sinkThrows']:raise RuntimeError('sink failed')
        result=await settle_run_result(dict(attempt=attempt,cancelled=lambda:case['cancelled'],
            collectOutput=lambda:[dict(type='text',text='partial')],collectDiagnostic=lambda:case['diagnostic'] if case['diagnostic'] is not None else UNDEFINED,
            onError=report,signal=tracked,onAbort=on_abort))
        rows.append(dict(kind='result',value=result,reports=reports,removed=removed))
    for fails in (False,True):
        controller=AbortController();trace=[];gate=asyncio.Event();failure=RuntimeError('teardown failed')
        def cancel():trace.append('cancel')
        async def teardown():
            trace.append('teardown');await gate.wait()
            if fails:raise failure
            trace.append('exited')
        on_abort=lambda *_:None;controller.signal.addEventListener('abort',on_abort)
        result=asyncio.get_running_loop().create_future();result.set_result(dict(output=[],stopReason='completed'))
        handle=subprocess_run_handle(dict(id='external',result=result,signal=controller.signal,onAbort=on_abort,requestCancel=cancel,teardown=teardown))
        first=handle.dispose();second=handle.dispose();before=list(trace);gate.set()
        observed=await asyncio.gather(first,second,return_exceptions=True)
        rows.append(dict(kind='dispose',same=first is second,before=before,after=trace,errorIdentity=not fails or all(value is failure for value in observed)))
    for value in [0,-1,True,1,1.5,float('inf'),float('nan')]:
        try:assert_positive_finite('backend','timeout',value);result=True
        except Exception as error:result=str(error)
        rows.append(dict(kind='timing',value=result))
    return rows


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_external_settlement.mts','Never-reject external result settlement, local cancellation priority, contained sinks, UTF-8 diagnostic bounding, exact memoized disposal including shared rejection, timing bound validation. OS process cleanup remains a separate consumer qualification.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/out_of_process.py'],prepare=prepare)
