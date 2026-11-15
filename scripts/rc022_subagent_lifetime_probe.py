"""Pair interrupt authority, memoized cleanup and parked tree waits."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import weakref
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
from scripts.rc022_tree_membership_probe import Agent


async def observe():
    from dsh.subagent.lifetime import SubagentLifetime,future,contain
    from dsh.subagent.tree import SubagentTree
    from dsh.subagent.activation import ChildLock
    from dsh.core.abort import AbortController
    from dsh.core.session.json import UNDEFINED
    rows=[]
    def fixture():
        trace=[];root=Agent('root');parent=Agent('parent','subagent',True);child=Agent('child','subagent',True)
        live={agent.id:agent for agent in (root,parent,child)}
        ctx=NS(get=lambda name:NS(get=live.get) if name=='agents' else None,logger=NS(warn=lambda value:trace.append('warning')))
        tree=object.__new__(SubagentLifetime);SubagentTree.__init__(tree,ctx,NS(identityOf=lambda session:None,emitLifecycle=lambda *args:trace.append('end')))
        tree.tasks=set();tree.materializations=set();tree.locks=ChildLock();tree.root_pools=weakref.WeakKeyDictionary()
        a=NS(kind='local',childId='child',runId='run',provider='test',root=root,ancestors=['root','parent'],path='worker/nested',
            result=contain(future()),closing=None,accepted=False,delivery='caller',failureAt=None,structured=None,outputStart=0,poke=future(),omitClosingText=False)
        async def idle():trace.append('idle')
        async def flush(session):trace.append('flush')
        async def dispose():trace.append('handle')
        child.status='idle';child.inbox=NS(nextTurn=[],nextStep=[])
        child.session.snapshotEvents=lambda cut:[]
        child.ctx=NS(get=lambda name:NS(flush=flush))
        child.cancel=lambda cause,options=None:trace.append(dict(cancel=cause,options=options))
        child.whenIdle=idle
        a.handle=NS(agent=child,dispose=dispose);a.releaseSlot=lambda:trace.append('slot')
        tree.resident['child']=a
        tree.resident['parent']=NS(kind='local',handle=NS(agent=parent),root=root,ancestors=['root'],path='worker',closing=None)
        return tree,a,root,parent,child,live,trace
    for action in ('user','root','parent','outsider','stale','self','absent','closing','external'):
        tree,a,root,parent,child,live,trace=fixture();authority=dict(kind='ancestor',agent=root)
        if action=='user':authority=dict(kind='user')
        elif action=='parent':authority['agent']=parent
        elif action=='outsider':authority['agent']=Agent('outsider');live['outsider']=authority['agent']
        elif action=='stale':live['root']=Agent('root')
        elif action=='self':authority['agent']=child
        elif action=='absent':tree.resident.pop('child')
        elif action=='closing':a.closing=future()
        elif action=='external':
            a.kind='external';a.controller=AbortController();a.controller.signal.add_listener('abort',lambda reason:trace.append(dict(abort=reason)))
            def dispose(_):
                trace.append('dispose');done=future();done.set_result(None);return done
            tree.dispose=dispose
        row=dict(kind='interrupt',action=action)
        try:tree.interrupt('child',authority)
        except Exception as error:row['error']=dict(code=getattr(error,'code',None),message=str(error))
        row['trace']=trace;rows.append(row)
    for action in ('local-stop','local-settle','handle-failure','external-stop','external-result-failure'):
        tree,a,root,parent,child,live,trace=fixture();tree.resident.pop('parent')
        descendant=NS();tree.resident['descendant']=descendant
        failure=RuntimeError('provider failure')
        if action=='handle-failure':
            async def fail():trace.append('handle');raise failure
            a.handle.dispose=fail
        if action.startswith('external'):
            a.kind='external';a.controller=AbortController()
            a.controller.signal.add_listener('abort',lambda reason:trace.append(dict(abort=reason)))
            result=contain(future())
            async def release():
                trace.append('handle')
                if not result.done():result.set_result(dict(output=[],stopReason='completed'))
            a.run=NS(result=result,dispose=release)
            if action=='external-result-failure':result.set_exception(failure)
        operation=tree.dispose(a) if action not in ('local-settle','external-result-failure') else tree.close(a,lambda:tree.finish_disposal(a,False))
        same=operation is tree.dispose(a);row=dict(kind='dispose',action=action,same=same,cutoff=a.closing is operation)
        try:await asyncio.shield(operation)
        except Exception as error:row['error']=getattr(error,'code',None)
        try:row['result']=await asyncio.shield(a.result)
        except Exception as error:row['resultErrorSame']=error is failure
        row.update(trace=trace,resident=list(tree.resident),descendantSame=tree.resident['descendant'] is descendant)
        rows.append(row)
    tree,a,root,parent,child,live,trace=fixture();tree.resident.pop('parent');child.inbox.nextTurn=[{}]
    rows.append(dict(kind='parked',joined=await tree.wait_for_tree_work(root),resident='child' in tree.resident))
    tree,a,root,parent,child,live,trace=fixture();observation=a.poke
    states=[tree.settlement_state(a,observation)];child.inbox.nextTurn=[{}];states.append(tree.settlement_state(a,observation))
    a.failureAt=0;states.append(tree.settlement_state(a,observation));tree.wake(a);states.append(tree.settlement_state(a,observation));a.closing=future();states.append(tree.settlement_state(a,a.poke))
    rows.append(dict(kind='readiness',states=states))
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_subagent_lifetime.mts','Ancestor interrupt authority, parked inbox preservation, synchronous shared close cutoff, resource/result ordering and independent descendant residency.',
        [Path(__file__).resolve(),ROOT/'dsh/subagent/lifetime.py',ROOT/'dsh/subagent/tree.py',ROOT/'dsh/subagent/activation.py'])
