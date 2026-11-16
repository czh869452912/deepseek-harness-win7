import asyncio
import json

import pytest

from dsh.boot.app_boot import boot
from dsh.boot.plugin_registry import _load
from dsh.boot.plugin_registry_current import CURRENT_HARNESS_PLUGIN_CLASSES as CANDIDATE
from dsh.core.session.json import UNDEFINED
from dsh.core.abort import NEVER_ABORTED
from dsh.llm.message import create_user_message
from scripts.oracles.agent_machine_current_python import ScriptAdapter
from scripts.oracles.generate_agent_machine_current_cases import response


@pytest.mark.asyncio
async def test_candidate_loader_v4_agent_native_tool_and_directory_consumers(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir();(workspace/'report.txt').write_text('native current read',encoding='utf-8')
    config=tmp_path/'root.json';config.write_text('[]',encoding='utf-8');requests=[]
    call=dict(type='tool-call',id='read-call',name='read',arguments=json.dumps(dict(file_path='report.txt')))
    script=[[dict(type='block-start',index=0,blockType='tool-call'),dict(type='tool-call-delta',index=0,id=call['id'],name=call['name'],argumentsDelta=call['arguments']),dict(type='block-end',index=0,block=call),dict(type='finish',reason=dict(kind='tool-calls'))],response('done')]
    # Agent precedes its projection dependency to exercise Loader injection.
    specifications=[('agent',{}),('session',{}),('llm',{}),('tools',{}),('tool-executor-native',{}),('system-prompt',{}),('working-directory',dict(defaultDirectory=str(workspace))),('session-projection',{}),('fs-local',dict(cwd=str(tmp_path))),('fs-observation-policy',{}),('tool-fs',dict(readImage=False,write=False,edit=False)),('session-persistence-jsonl',dict(root=str(tmp_path/'sessions'),compression='none')),('agent-loop',dict(agents=[]))]
    rows=[dict(id=name,name='@deepseek-ai/dsh-'+name,config=config) for name,config in specifications]
    def prepare(ctx):
        for row in rows:ctx.loader.harness_plugins[row['name']]=_load(row['name'],CANDIDATE[row['name']])
        def adapter(child):child.llm.registerAdapter(['script'],ScriptAdapter(dict(script=script)))
        ctx.inject(['llm'],adapter)
        def request(value,next_fn):requests.append(value);return next_fn()
        ctx.on('llm/stream',request)
    ctx=await boot('candidate-agent',str(config),[dict(insert=rows)],prepare);lease=None
    try:
        assert ctx.sessions.format_version==ctx.sessionProjections.format_version==ctx.agents.format_version==ctx.tools.contract_version==4
        lease=await ctx.agents.create(dict(sessionId='booted',agentOptions=dict(provider='script',model='model')))
        lease.agent.followup(create_user_message(dict(content=[dict(type='text',text='Read the report')],source=dict(kind='user'))))
        await asyncio.wait_for(lease.agent.whenIdle(),5)
        events=lease.agent.session.snapshotEvents();results=[event for event in events if event['type']=='tool/result']
        assert len(requests)==2 and len(results)==1,[(event['type'],event.get('data')) for event in events]
        assert 'native current read' in json.dumps(results[0])
        assert 'report.txt' in json.dumps(results[0])
        assert lease.agent.session.requestHeader() is not UNDEFINED
        header=lease.agent.session.requestHeader();assert 'read' in {tool['name'] for tool in header['tools']}
        assert 'run_code' not in {tool['name'] for tool in header['tools']}
        assert ctx.agents.turnBoundaryOf(lease.agent.session) is not None
        assert str(workspace) in await ctx.workingDirectory.ensure(lease.agent,NEVER_ABORTED)
        (tmp_path/'candidate-agent-observations.json').write_text(json.dumps(dict(eventTypes=[event['type'] for event in events],header=header,requests=len(requests)),default=str,indent=2),encoding='utf-8')
    finally:
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()
