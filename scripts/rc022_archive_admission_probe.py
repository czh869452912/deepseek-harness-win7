"""Pair archive activity, stop fan-out and model-step admission."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.subagent.archive_admission import install_subagent_archive_admission
    from dsh.cordis.awaiting import await_callback_result
    rows=[]
    for action in ('headers','resident','inherited-label','idle','offline','ordinary-fork','cycle','stop-failure','no-workspace','no-running'):
        trace=[];hooks={}
        def agent(identity,parent=None,origin=None,own=True):
            return NS(id=identity,status='running',session=NS(header=dict(id=identity,**(dict(parentSession=parent) if parent else {}),**(dict(origin=origin) if origin else {})),
                isOwnSeq=lambda seq:own),cancel=lambda reason:trace.append(identity))
        root=agent('root');parent=agent('parent','root','subagent');child=agent('child','parent','subagent',action!='inherited-label')
        live={'root':root,'parent':parent,'child':child}
        if action=='idle':parent.status='idle'
        elif action=='offline':live.pop('parent')
        elif action=='ordinary-fork':parent.session.header.pop('origin')
        elif action=='cycle':parent.session.header['parentSession']='child'
        elif action=='stop-failure':
            def fail(reason):trace.append('parent');raise RuntimeError('cancel failed')
            parent.cancel=fail
        elif action=='no-running':parent.status=child.status='idle'
        services=dict(agents=NS(get=live.get,list=lambda:list(live.values())),workspaceRegistry=NS(archivedSessionIds=['root']))
        if action=='no-workspace':services.pop('workspaceRegistry')
        ctx=NS(get=services.get,on=lambda event,callback:hooks.update({event:callback}),logger=NS(warn=lambda value:trace.append('warning')))
        install_subagent_archive_admission(ctx,lambda value:['root','parent'] if action=='resident' and value is child else None,
            lambda session:dict(seq=1,label='Label'))
        activity=await hooks['workspace/session-activity'](dict(sessionId='root'),lambda:[dict(kind='other',items=[])])
        decision=await await_callback_result(hooks['agent/pre-step'](dict(agent=child),lambda:dict(kind='enter')))
        hooks['workspace/session-stop'](dict(sessionId='root'))
        rows.append(dict(action=action,activity=activity,decision=decision,trace=trace))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_archive_admission.mts','Workspace archive activity and cancellation, verified resident ancestry versus header fallback, ordinary fork/cycle/offline boundaries and own-identity labels.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/archive_admission.py',ROOT/'dsh/subagent/manager.py'])
