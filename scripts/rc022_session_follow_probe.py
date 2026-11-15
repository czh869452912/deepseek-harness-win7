"""Pair Web opening cuts, mixed increments and explicit cold activation."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
WORKSPACE=None


async def observe(workspace=None):
    from scripts.rc022_subagent_fixture import setup
    from dsh.api.session_history_authorized import SessionHistoryController
    from dsh.api.session_web_authorized import SessionWebController
    from dsh.api.session_agents_authorized import AuthorizedSessionAgents
    from dsh.typert.current import CurrentTypertRegistry
    from dsh.core.abort import AbortController
    from dsh.core.session.plugin_records import appendPluginRecord
    fixture=await setup((workspace or WORKSPACE)/'native');ctx=fixture.ctx;rows=[];tasks=[];promotions=[];opened=[];streams=[]
    try:
        await ctx.plugin(CurrentTypertRegistry)
        ctx.set_service('agentDefaultModel',NS(currentSelection=lambda:dict(provider='script',model='model')))
        agents=AuthorizedSessionAgents(ctx);history=SessionHistoryController(ctx)
        def promote(observation):
            promotions.append(observation.header.id)
            async def resume():
                try:
                    result=await agents.resolveObservedAgent(observation)
                    if 'error' in result:raise result['error']
                finally:observation.dispose()
            tasks.append(asyncio.ensure_future(resume()))
        web=SessionWebController(ctx,history,promote)
        handle=await ctx.agents.create(dict(sessionId='follow',meta=dict(cwd='C:/follow'),agentOptions=dict(provider='script',model='model')))
        session=handle.agent.session
        def emit(frame):ctx.emit('agent/assistant-stream',dict(agent=handle.agent,frame=frame))
        appendPluginRecord(session,'plugin:fixture/tick',dict(value=0))
        emit(dict(type='start',attemptId='attempt',revision=1,turn=1,step=1))
        query=ctx.sessionQuery.observeSession;race=[True]
        async def observe(identity,options=None):
            value=await query(identity,options);opened.append(value)
            if race[0]:
                race[0]=False
                appendPluginRecord(session,'plugin:fixture/tick',dict(value=1))
                emit(dict(type='chunk',attemptId='attempt',revision=2,index=0,time=4,chunk=dict(type='text-delta',index=0,text='partial')))
            return value
        ctx.sessionQuery.observeSession=observe
        address=dict(kind='session',sessionId='follow')
        live=web.follow(dict(address=address,assistantStream=True,activate=True),fixture.signal);streams.append(live)
        opening=await live.__anext__()
        rows.append(dict(name='live-opening',value=opening,promotions=list(promotions),leaseReleased=opened[-1]._disposed))
        emit(dict(type='end',attemptId='attempt',revision=3,index=1,outcome=dict(kind='abandoned')))
        appendPluginRecord(session,'plugin:fixture/tick',dict(value=2))
        rows.append(dict(name='uncovered-mixed',values=[await live.__anext__() for _ in range(3)]))
        await live.aclose();await handle.dispose()
        passive=web.follow(dict(address=address,assistantStream=True),fixture.signal);streams.append(passive)
        rows.append(dict(name='cold-default-passive',value=await passive.__anext__(),promotions=list(promotions),agentAbsent=ctx.agents.get('follow') is None,leaseReleased=opened[-1]._disposed))
        await passive.aclose()
        active=web.follow(dict(address=address,activate=True),fixture.signal);streams.append(active)
        value=await active.__anext__()
        rows.append(dict(name='promotion-before-opening',cursor=value['cursor'],promotions=list(promotions),leaseReleased=opened[-1]._disposed))
        await active.aclose();await asyncio.gather(*tasks)
        rows.append(dict(name='promotion-outlives-consumer',attached=ctx.agents.get('follow') is not None))
        missing=web.follow(dict(address=dict(kind='subagent',parentSessionId='parent',childSessionId='missing',mode='unknown')),fixture.signal);streams.append(missing)
        try:await missing.__anext__()
        except Exception as error:rows.append(dict(name='missing-subagent',code=error.code,details=error.details))
        abort=AbortController();abort.abort();cancelled=web.follow(dict(address=address),abort.signal);streams.append(cancelled)
        try:await cancelled.__anext__()
        except Exception as error:rows.append(dict(name='already-cancelled',nameOfError=getattr(error,'name',type(error).__name__)))
        def normalize(value):
            if isinstance(value,dict):
                return {key:(0 if key=='createdAt' or key=='time' and 'seq' in value and 'type' in value else normalize(item)) for key,item in value.items()}
            if isinstance(value,(list,tuple)):return [normalize(item) for item in value]
            return value
        return normalize(json.loads(json.dumps(rows)))
    finally:
        for stream in streams:await stream.aclose()
        await asyncio.gather(*tasks,return_exceptions=True)
        await ctx.fiber.dispose()


def prepare(output):
    global WORKSPACE
    WORKSPACE=output/'files';WORKSPACE.mkdir();path=output/'workspace.json';path.write_text(json.dumps(str(WORKSPACE)),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_session_follow.mts','Actual Agent/Session/JSONL/query/history/Assistant buffers and ordinary activation: arrivals during opening, fixed-cut history plus uncovered mixed increments, baseline ordinal suppression, passive cold opening, opening lease release, explicit promotion before delivery that outlives a closed consumer, missing address mapping and pre-cancellation. Trusted Assistant frames are controlled notifications; complete SessionController boot remains separate.',
        [Path(__file__).resolve(),ROOT/'dsh/api/session_web_authorized.py',ROOT/'dsh/api/session_authorized.py'],prepare=prepare)
