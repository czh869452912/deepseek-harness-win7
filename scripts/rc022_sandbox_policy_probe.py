"""Live Session policy/projection/grant lifecycle versus fixed Source."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSession
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.sandbox.policy_current import CurrentSandboxPolicy,set_sandbox_mode
    class Projections(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    def session(identity,cwd=None,seed=None):
        header=dict(version=4,id=identity,createdAt=0,isSeeded=False)
        if cwd is not None:header['cwd']=cwd
        return CurrentSession.create(identity,seed,header,format_version=4)
    ctx=Context();await ctx.plugin(Projections);await ctx.plugin(CurrentSystemPrompt);roots=['C:/shared//root','C:/shared//root'];owner=await ctx.plugin(CurrentSandboxPolicy,dict(mode='workspace-write',workspaceRoot='C:/fallback/../root',additionalWritableRoots=roots));policy=ctx.sandboxPolicy;first=session('first','C:/workspace/../first');second=session('second');rows=[]
    async def context(active):
        assembly=await ctx.systemPrompt.assemble({} if active is None else dict(agent=NS(session=active)))
        return [entry for entry in assembly['contexts'] if entry['name']=='sandbox:policy']
    try:
        roots.append('C:/not-granted');rows.append(dict(name='default',value=policy.resolve(),first=policy.resolve(dict(session=first)),second=policy.resolve(dict(session=second))))
        before=policy.resolve(dict(session=first));remove=policy.registerWritableRoot(first,'C:/memory');remove_duplicate=policy.registerWritableRoot(first,'C:/memory');granted=policy.resolve(dict(session=first))
        rows.append(dict(name='grant',before=before,granted=granted,other=policy.resolve(dict(session=second)),agentless=policy.resolve(),resumed=policy.resolve(dict(session=session('first','C:/workspace/../first',first.snapshotEvents())))))
        remove();rows.append(dict(name='duplicate-owned',value=policy.resolve(dict(session=first))));remove_duplicate();rows.append(dict(name='removed',value=policy.resolve(dict(session=first)),snapshot=granted))
        class Grant(Plugin):
            inject=['sandboxPolicy']
            def apply(self,scope):scope.sandboxPolicy.registerWritableRoot(first,'C:/child-grant')
        child=await ctx.plugin(Grant);rows.append(dict(name='child-owned',value=policy.resolve(dict(session=first))));await child.dispose();rows.append(dict(name='child-disposed',value=policy.resolve(dict(session=first))))
        policy.registerWritableRoot(first,'C:/prompt-extra');rows.append(dict(name='workspace-context',value=await context(first)))
        set_sandbox_mode(first,'read-only');rows.append(dict(name='read-only',value=policy.resolve(dict(session=first)),context=await context(first),override=policy.overrideOf(first)))
        set_sandbox_mode(first,'danger-full-access');rows.append(dict(name='full',value=policy.resolve(dict(session=first)),approved=policy.resolve(dict(session=first,mode='workspace-write')),context=await context(first),other=policy.resolve(dict(session=second)),events=[dict(type=event['type'],data=event['data']) for event in first.snapshotEvents()]))
        rows.append(dict(name='resumed',value=policy.resolve(dict(session=session('first','C:/workspace/../first',first.snapshotEvents()))),context=await context(None)))
        for cwd in ('relative','C:/bad\0root'):
            try:policy.resolve(dict(session=session('invalid',cwd)))
            except Exception as error:rows.append(dict(name='invalid-session',cwd=cwd,error=dict(code=getattr(error,'code',None),message=getattr(error,'message',str(error)))))
        for root in ('relative','C:/bad\0root'):
            try:policy.registerWritableRoot(first,root)
            except Exception as error:rows.append(dict(name='invalid-grant',root=root,message=str(error)))
        await owner.dispose();rows.append(dict(name='unload',service=ctx.get('sandboxPolicy') is not None,context=await context(first)))
        return json.loads(json.dumps(rows))
    finally:await ctx.fiber.dispose()


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_sandbox_policy.mts','Actual v4 Session, projection and prompt: execution-world spelling, immutable configured/snapshot extra grants, exact Session identity, independent duplicate and child effect ownership, durable mode fold and approved precedence, resume without runtime grants, typed invalid recorded cwd, invalid grants, prompt contribution and unload.',[Path(__file__).resolve(),ROOT/'dsh/sandbox/policy_current.py'])
