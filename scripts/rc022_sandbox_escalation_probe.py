"""Current typed escalation, approval ordering and localized display reason."""
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.sandbox.escalation_current import validate_escalation_args,approve_escalation
    from dsh.cordis.utils import _UNDEFINED
    from dsh.core.abort import AbortController
    rows=[]
    class Error(Exception):pass
    def failure(error):return dict(error=getattr(error,'message',str(error)),code=getattr(error,'code',None),errorName=getattr(error,'name','Error'))
    for mode,reason in [(_UNDEFINED,_UNDEFINED),('workspace-write',_UNDEFINED),(_UNDEFINED,'orphan'),('workspace-write','\ufeff\u3000'),('workspace-write','\u0085')]:
        try:validate_escalation_args(mode,reason);rows.append(dict(name='validate',value='valid'))
        except Exception as error:rows.append(dict(name='validate',**failure(error)))
    cases=[(effective,mode,outcome,'both') for effective,mode in [('read-only','workspace-write'),('read-only','danger-full-access'),('workspace-write','read-only'),('danger-full-access','workspace-write'),('workspace-write','workspace-write')] for outcome in ('allowed-once','rejected','cancelled','unavailable')]
    cases += [('read-only','workspace-write','allowed-once','no-service'),('read-only','workspace-write','allowed-once','no-agent'),('workspace-write','workspace-write','allowed-once','no-service'),('read-only','workspace-write','cancelled','aborted'),('read-only','workspace-write','unknown','both')]
    for effective,mode,outcome,composition in cases:
        seen=[];controller=AbortController();original=Error('call cancelled');agent=object()
        async def request(ask):
            seen.append(dict(toolName=ask['toolName'],callId=ask['callId'],reason=ask['reason'],displayReason=ask['displayReason'],agent=ask['agent'] is agent,signal=ask['signal'] is controller.signal));return outcome
        if composition=='aborted':controller.abort(original)
        approval=dict(approver=None if composition=='no-service' else NS(request=request),agent=None if composition=='no-agent' else agent,toolName='pwsh',callId='call',signal=controller.signal)
        row=dict(name=effective+'>'+mode+'/'+outcome+'/'+composition,asked=seen)
        try:row['value']=await approve_escalation(dict(effectiveMode=effective,requestedMode=mode,justification='需要写入 "输出"\nverbatim',subject='command'),approval)
        except Exception as error:row.update(failure(error),originalError=error is original)
        rows.append(row)
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sandbox_escalation.mts','Current escalation argument pairing/JS whitespace, effective-mode equality, strict widening before service/agent lookup, four typed outcomes, exact audit and eight-locale display reasons and caller cancellation identity. Both use controlled structural approval collaborators; no external approval action.',[Path(__file__).resolve(),ROOT/'dsh/sandbox/escalation_current.py'])
