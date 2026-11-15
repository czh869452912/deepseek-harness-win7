"""Observe actual V4 factory publication, maintenance and rollback barriers."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe

async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.abort import AbortController
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import ToolsPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    from scripts.rc022_inbox_readers_probe import message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    rows=[]
    for action in ('visible','setup-wake','created-wake','setup-reject','created-reject','caller-setup','caller-ready','owner-created','commit','clear-failure'):
        ctx=Context();trace=[];row=dict(action=action);entered=asyncio.Event();release=asyncio.Event();late=asyncio.Event();controller=AbortController();primary=RuntimeError('primary');jobs=[];handles=[];captured=[];owners=[];calls=[]
        try:
            for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,ToolsPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
            await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]));ctx.get('llm').registerAdapter(['script'],ScriptAdapter(dict(script=[response() for _ in range(4)])))
            sessions,agents=ctx.get('sessions'),ctx.get('agents')
            class Owner(Plugin):
                inject=['agents']
                def apply(self,scope):owners.append(scope)
            owner=await ctx.plugin(Owner)
            def snapshot(stage,agent=None):
                trace.append(dict(stage=stage,session=sessions.get('subject') is not None,agent=agents.get('subject') is not None,
                                  turns=0 if agent is None else len([e for e in agent.session.events if e['type']=='turn/start'])))
            ctx.on('session/created',lambda session:snapshot('session'))
            ctx.on('agent/disposed',lambda payload:trace.append(dict(stage='agent-disposed')))
            ctx.on('session/disposed',lambda session:trace.append(dict(stage='session-disposed')))
            async def setup(scope,agent):
                captured.append(agent);snapshot('setup',agent)
                original=agent.cancel
                def cancel(cause,options=None,**kwargs):calls.append(dict(kind=cause['kind'],keep=(options or {}).get('keepInbox',False)));return original(cause,options,**kwargs)
                agent.cancel=cancel
                if action in ('setup-wake','setup-reject','caller-setup'):agent.followup(message('queued'))
                if action=='setup-reject':raise primary
                if action=='caller-setup':entered.set();await release.wait();late.set()
                if action=='commit':return SimpleNamespace(commit=lambda:snapshot('commit',agent))
            async def created(payload):
                agent=payload['agent'];snapshot('created',agent)
                row['source']=payload['source'];row['signal']=payload.get('signal') is not None
                if action in ('created-wake','created-reject','owner-created'):agent.followup(message('queued'))
                if action in ('owner-created','created-reject'):entered.set();await release.wait()
                if action=='created-reject':raise primary
                snapshot('created-end',agent)
            ctx.on('agent/created',created)
            async def create():
                try:
                    handle=await owners[0].get('agents').create(dict(sessionId='subject',agentOptions=dict(provider='script',model='model'),setup=setup,signal=controller.signal));handles.append(handle);return handle
                except Exception as error:row['rejected']=True;row['same']=error is primary;return None
            task=asyncio.ensure_future(create());jobs.append(task)
            if action in ('caller-setup','owner-created','created-reject'):
                await asyncio.wait_for(entered.wait(),3)
                if action=='caller-setup':controller.abort(primary);await asyncio.wait_for(task,3);release.set();await asyncio.wait_for(late.wait(),3)
                elif action=='owner-created':
                    closing=asyncio.ensure_future(owner.dispose());jobs.append(closing);await asyncio.sleep(0);row['waiting']=not closing.done();snapshot('unloading',captured[0]);release.set();await asyncio.wait_for(asyncio.gather(task,closing),3)
                else:release.set()
            handle=await asyncio.wait_for(task,3)
            if handle is not None:
                if action=='caller-ready':controller.abort(primary);handle.agent.followup(message('after-ready'))
                if action=='clear-failure':
                    entered.clear()
                    async def maintenance(signal):entered.set();await release.wait();row['cancelled']=signal.aborted
                    work=handle.agent.runMaintenance(maintenance);jobs.append(work);await entered.wait();handle.agent.followup(message('queued'))
                    def fail_clear():raise primary
                    handle.agent.inbox.clear=fail_clear
                    try:handle.agent.cancel(dict(kind='user'))
                    except Exception as error:row['cancelSame']=error is primary
                    async def dispose():
                        try:await handle.dispose()
                        except Exception as error:row['disposeSame']=error is primary
                    closing=asyncio.ensure_future(dispose());jobs.append(closing);await asyncio.sleep(0);row['waiting']=not closing.done();snapshot('stopping',handle.agent);release.set();await asyncio.gather(work,closing)
                await asyncio.wait_for(handle.agent.whenIdle(),3)
            agent=captured[0]
            row['pending']=[msg['content'][0]['text'] for msg in agent.inbox.nextTurn]
            row['turns']=len([event for event in agent.session.events if event['type']=='turn/start'])
            row['messages']=[event['data']['content'][0]['text'] for event in agent.session.events if event['type']=='user/message']
            row['idle']=agent.status=='idle'
            if handle is not None and action!='clear-failure':await handle.dispose()
            row.update(trace=trace,cancels=calls,removed=not sessions.list() and not agents.list())
            rows.append(json.loads(json.dumps(row)))
        finally:
            release.set()
            if jobs:await asyncio.gather(*jobs,return_exceptions=True)
            if handles:await asyncio.gather(*(handle.dispose() for handle in reversed(handles)),return_exceptions=True)
            await ctx.fiber.dispose()
    return rows

if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_factory_publication.mts','Real loop Session publication before setup, Agent serial announcement after setup/commit under maintenance, queued wakes, failure retention, caller cancellation scope and owner-disposal publication barrier.',[Path(__file__).resolve(),ROOT/'dsh/core/agent_loop_current.py',ROOT/'dsh/core/agent_lifecycle_current.py',ROOT/'dsh/core/react_loop_current.py'])
