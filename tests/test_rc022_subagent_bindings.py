import asyncio
import json

import pytest

from dsh.boot.app_boot import boot
from dsh.boot.plugin_registry import _load
from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES as CANDIDATE
from dsh.core.abort import NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from scripts.oracles.agent_machine_current_python import ScriptAdapter
from scripts.oracles.generate_agent_machine_current_cases import response


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['spawn','fork'])
async def test_actual_candidate_loader_delegation_control_and_cold_continuation(tmp_path,provider):
    config=tmp_path/'root.json';config.write_text('[]',encoding='utf-8')
    specs=[('agent',{}),('session',{}),('llm',{}),('tools',{}),('tool-executor-native',{}),('system-prompt',{}),('working-directory',dict(defaultDirectory=str(tmp_path))),('session-projection',{}),('fs-local',dict(cwd=str(tmp_path))),('session-persistence-jsonl',dict(root=str(tmp_path/'sessions'),compression='none')),('session-query-sqlite',dict(path=':memory:',openAt='never')),('agent-loop',dict(agents=[])),('subagent',{}),('subagent-'+provider+'-in-process',{}),('tool-subagent',dict(provider=provider)),('tool-subagent-control',dict(interrupt=False))]
    rows=[dict(id=name,name='@deepseek-ai/dsh-'+name,config=value) for name,value in specs]
    def prepare(ctx):
        for row in rows:ctx.loader.harness_plugins[row['name']]=_load(row['name'],CANDIDATE[row['name']])
        ctx.inject(['llm'],lambda child:child.llm.registerAdapter(['script'],ScriptAdapter(dict(script=[response('child answer') for _ in range(20)]))))
    ctx=await boot('candidate-subagent',str(config),[dict(insert=rows)],prepare);lease=None
    async def call(name,args):return await ctx.tools.execute(ToolExecutionInput(name+'-call',name,args,agent=lease.agent,signal=NEVER_ABORTED))
    try:
        lease=await ctx.agents.create(dict(sessionId='lead',agentOptions=dict(provider='script',model='model')));parent=lease.agent
        parent.session.append('turn/start',dict(turn=1));parent.session.append('turn/end',dict(turn=1,reason=dict(kind='completed')))
        result=await call('subagent',dict(prompt='Focused task',description='Loader child',name='worker'))
        assert not result.is_error,result.content
        assert result.value==dict(kind='activation',name='worker')
        await asyncio.wait_for(ctx.subagents.waitForTreeWork(parent),5);await asyncio.wait_for(parent.whenIdle(),5)
        identity=await ctx.subagents.resolveName(parent,'worker',NEVER_ABORTED)
        assert ctx.subagents.rootOf(parent) is parent
        assert ctx.agents.get(identity) is None
        listing=await call('list_agents',{})
        assert not listing.is_error,listing.content
        assert any(item['name']=='worker' and item['status']=='inactive' for item in listing.value)
        followup=await call('send_message',dict(agent='worker',message='Continue the same task'))
        assert not followup.is_error,followup.content
        await asyncio.wait_for(ctx.subagents.waitForTreeWork(parent),5);await asyncio.wait_for(parent.whenIdle(),5)
        observed=await ctx.sessionQuery.observeSession(identity,{})
        try:
            events=list(observed.events)
            assert sum(event['type']=='subagent/descriptor' for event in events)==1
            assert sum(event['type']=='turn/end' for event in events)>=2
        finally:observed.dispose()
        assert ctx.tools.get('interrupt_agent') is None
        (tmp_path/'candidate-subagent-observations.json').write_text(json.dumps(dict(provider=provider,activation=result.value,listing=listing.value,coldResumeId=identity,eventTypes=[event['type'] for event in events]),indent=2),encoding='utf-8')
    finally:
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()
