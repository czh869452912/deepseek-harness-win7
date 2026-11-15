"""Pair Session tool history, request projection, and actual Agent consumers."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    a = dict(name='search', description='search tool', parameters={})
    b = dict(name='fetch', description='fetch tool', parameters={})
    deferred = dict(a, deferLoading=True)
    prompt = dict(id='user', role='user', source=dict(kind='user'), content=[dict(type='text', text='hi')])
    def update(identity, blocks):
        return dict(id=identity, role='developer', source=dict(kind='tool-registry'), content=blocks)
    added = update('add', [dict(type='tool-addition', toolName='fetch'), dict(type='text', text='keep')])
    removed = update('remove', [dict(type='tool-removal', toolName='search')])
    restored = update('restore', [dict(type='tool-addition', toolName='search')])
    duplicate = update('duplicate', [dict(type='tool-addition', toolName='fetch')])
    initial = update('initial', [dict(type='tool-addition', toolName='search')])
    history = dict(tools=[a], updates=[dict(messageId='add', additions=[b]), dict(messageId='remove', additions=[]), dict(messageId='restore', additions=[a])])
    rows = []
    for mode in (None, 'in-history', 'addition-only'):
        for action in ('plain', 'history', 'missing', 'prefix', 'empty', 'deferred', 'deferred-activate', 'duplicate', 'earlier', 'removed'):
            messages, tools, current = [prompt, added, removed, restored], [a,b], history
            if action == 'plain':
                messages, current = [prompt], dict(tools=[a,b], updates=[])
            elif action == 'missing':
                current = None
            elif action == 'prefix':
                messages = [prompt, added]
            elif action == 'empty':
                messages, tools, current = [prompt, added], [b], dict(tools=[], updates=[dict(messageId='add', additions=[b])])
            elif action == 'deferred':
                messages, tools, current = [prompt, added], [deferred,b], dict(tools=[deferred], updates=[dict(messageId='add', additions=[b])])
            elif action == 'deferred-activate':
                messages, tools, current = [prompt, initial, removed, restored], [deferred], dict(tools=[deferred], updates=[dict(messageId='initial', additions=[deferred]), dict(messageId='remove', additions=[]), dict(messageId='restore', additions=[deferred])])
            elif action == 'duplicate':
                messages = [prompt, added, duplicate]
                current = dict(tools=[a], updates=[dict(messageId='add', additions=[b]), dict(messageId='duplicate', additions=[b])])
            elif action == 'earlier':
                messages, current = [prompt, initial, added], dict(tools=[a], updates=[dict(messageId='add', additions=[b])])
            elif action == 'removed':
                messages, tools, current = [prompt, added, removed], [b], dict(tools=[a], updates=history['updates'][:2])
            rows.append(dict(kind='project', action=action, mode=mode, messages=messages, tools=tools, history=current))
    def header(seq, tools, reason='change', **kwargs):
        return dict(seq=seq, type='request/header', data=dict(header=dict(config=dict(provider='p',model='m'), tools=tools), reason=reason, **kwargs))
    def event(seq, message, header_seq=None):
        return dict(seq=seq, type='developer/message', data=dict(message=message, **({} if header_seq is None else dict(headerSeq=header_seq))))
    base = [header(0,[a],'initial'),header(1,[a,b]),event(2,added,1),header(3,[b]),event(4,removed),header(5,[a,b]),event(6,restored,5)]
    for action, events in [('empty',[]),('normal',base),('redeclare',base+[header(7,[a,dict(b,description='new')])]),('series',base+[header(7,[a,b],'series')]),('starts-series',base+[header(7,[a,b],startsSeries=True)]),('unmatched-header',base[:2]),('missing-definition',[event(0,added)]),('numeric-keys',[header(0,[dict(a,parameters={'2':2.0,'1':1})],'initial'),header(1,[dict(a,parameters={'1':1.0,'2':2})])])]:
        rows.append(dict(kind='fold', action=action, events=events))
    return rows


def observe_values():
    from dsh.llm.tool_updates import project_tool_updates
    from dsh.core.session.tool_history import ToolHistoryProjection
    rows = []
    for case in cases():
        row = dict(kind=case['kind'], action=case['action'])
        if case['kind'] == 'project':
            row['mode'] = case['mode']
            before = json.dumps(case)
            result = project_tool_updates(case['messages'],case['tools'],case['mode'],case['history'])
            row.update(result=result, sameMessages=result['messages'] is case['messages'], sameTools=result['tools'] is case['tools'], unchanged=json.dumps(case)==before)
        else:
            fold, snapshots = ToolHistoryProjection(), []
            try:
                for event in case['events']:
                    fold.apply(event)
                    snapshots.append(fold.snapshot())
                row['snapshots'] = snapshots
                row['repeat'] = fold.snapshot() is fold.snapshot()
            except Exception as error:
                row['error'] = str(error)
        rows.append(row)
    return rows


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.session.current_session import CurrentSessionStore
    from dsh.session.projections import SessionProjectionRegistry
    from dsh.core.agent_current import CurrentAgentPlugin
    from dsh.core.agent_loop_current import CurrentAgentLoopPlugin
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.llm.runtime_current import CurrentLlmRuntime
    from scripts.oracles.agent_machine_current_python import ScriptAdapter
    from scripts.oracles.generate_agent_machine_current_cases import response
    from scripts.rc022_inbox_readers_probe import message
    class Store(Plugin):
        def apply(self,ctx):CurrentSessionStore(ctx,4)
    class Registry(Plugin):
        def apply(self,ctx):SessionProjectionRegistry(ctx,4)
    class Adapter(ScriptAdapter):
        async def resolve_model(self,provider,model,signal=None):
            result = await super().resolve_model(provider,model,signal)
            if self.mode is not None:result['toolUpdate']=self.mode
            return result
        async def stream(self,request):
            requests.append(dict(tools=request.get('tools',[]), updates=[m['content'] for m in request['messages'] if m['role']=='developer'],
                                 history=[len(request['toolHistory']['tools']), len(request['toolHistory']['updates'])]))
            async for chunk in super().stream(request):yield chunk
    rows = observe_values()
    for mode in (None,'in-history','addition-only'):
        ctx, requests, handle, errors = Context(), [], None, []
        try:
            for plugin in (CurrentLlmRuntime,Store,Registry,CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentAgentPlugin):await ctx.plugin(plugin)
            await ctx.plugin(CurrentAgentLoopPlugin,dict(agents=[]))
            ctx.on('agent/error',lambda value:errors.append(str(value['error'])))
            adapter=Adapter(dict(script=[response() for _ in range(7)]));adapter.mode=mode
            ctx.llm.registerAdapter(['script'],adapter)
            def tool(name, description=None):
                return ctx.tools.register(dict(name=name,description=description or name+' tool',parameters={},output=dict(schema=dict(type='string'),render=lambda a,v:[]),execute=lambda a,e:'done'))
            remove_a = tool('search')
            handle=await ctx.agents.create(dict(sessionId='updates',agentOptions=dict(provider='script',model='model')))
            agent=handle.agent
            for step in range(7):
                if step==1:remove_b=tool('fetch')
                if step==2:remove_a()
                if step==3:remove_a=tool('search')
                if step==4:
                    remove_b();remove_b=tool('fetch','changed')
                if step==5:adapter.mode='in-history' if mode is None else None
                agent.followup(message('step-'+str(step)));await agent.whenIdle()
            events=agent.session.snapshotEvents();headers=[e for e in events if e['type']=='request/header'];updates=[e for e in events if e['type']=='developer/message']
            restored=type(agent.session).create('restored',events,format_version=4)
            rows.append(dict(kind='driver',mode=mode,requests=requests,errors=errors,
                restored=restored.toolHistory()==agent.session.toolHistory(),cached=agent.session.toolHistory() is agent.session.toolHistory(),
                headers=[dict(reason=e['data']['reason'],series=e['data'].get('startsSeries',False),tools=[t['name'] for t in e['data']['header'].get('tools',[])]) for e in headers],
                additions=[dict(content=e['data']['message']['content'],bound=next((i for i,h in enumerate(headers) if h['seq']==e['data'].get('headerSeq')),None)) for e in updates],
                endings=[e['data']['reason']['kind'] for e in events if e['type']=='turn/end']))
        finally:
            if handle is not None:await handle.dispose()
            await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


def prepare(output):
    path=output/'cases.json';path.write_text(json.dumps(cases()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_tool_updates.mts','Incremental Session tool history and route-aware declarations through actual Agent request headers and adapter dispatch.',
        [Path(__file__).resolve(),ROOT/'dsh/core/session/tool_history.py',ROOT/'dsh/core/session/current_session.py',ROOT/'dsh/core/react_loop_current.py',ROOT/'dsh/llm/model_info.py',ROOT/'dsh/llm/runtime_current.py',ROOT/'dsh/llm/tool_updates.py'],prepare)
