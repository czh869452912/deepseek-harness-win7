import asyncio
import json
import sys
from pathlib import Path

import pytest

from dsh.core.abort import AbortController,NEVER_ABORTED
from dsh.core.tools import ToolExecutionInput
from dsh.cordis.awaiting import await_callback_result
from scripts.rc022_candidate_fixture import setup

PEER=Path(__file__).resolve().parents[1]/'scripts/oracles/rc022_mcp_resource_peer.py'


@pytest.mark.asyncio
@pytest.mark.parametrize('capabilities',[True,False])
async def test_actual_stdio_generation_resource_capabilities_instructions_cancel_and_unload(tmp_path,capabilities):
    log=tmp_path/'peer.jsonl';counter=tmp_path/'counter.txt'
    config=dict(transport='stdio',serverName='docs',command=sys.executable,
        args=[str(PEER),str(log),str(counter),'resources' if capabilities else 'none'],
        reconnect=dict(enabled=False),failOnStartupError=True)
    ctx=await setup(tmp_path,extra=[('mcp-resources',{}),('mcp-client',config)]);lease=None
    try:
        entry=next(entry for entry in ctx.loader.entries() if entry.options.get('id')=='mcp-client')
        connection=entry.fiber.plugin.connection;process=connection.client.proc
        assert connection._connected_at is not None
        lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='m')))
        async def call(name,args,signal=NEVER_ABORTED):
            return await ctx.tools.execute(ToolExecutionInput(name,name,dict(server='docs',**args),agent=lease.agent,signal=signal))
        listed=await call('list_mcp_resources',dict(cursor=''))
        templates=await call('list_mcp_resource_templates',{})
        assert not listed.is_error and not templates.is_error
        assert bool(listed.value['resources'])==capabilities
        assert bool(templates.value['resourceTemplates'])==capabilities
        if capabilities:
            assert 'generation' not in listed.value['resources'][0]
            invalid=await call('list_mcp_resources',dict(cursor='bad'))
            assert invalid.is_error
        read=await call('read_mcp_resource',dict(uri='doc://a'))
        assert not read.is_error and read.value['contents'][0]['blob']=='YWJj'
        prompt=await ctx.systemPrompt.assemble(dict(agent=lease.agent,scope=lease.agent.ctx))
        instructions=next(row for row in prompt['sections'] if row['name']=='mcp:docs')
        assert instructions['text']=='### MCP server: docs\n\nUse literal {{model}} for generation 1'
        assert instructions['interpolate'] is False
        if capabilities:
            abort=AbortController()
            held=asyncio.create_task(call('list_mcp_resources',dict(cursor='hold'),abort.signal))
            async def request_seen():
                while not any(row['packet'].get('params',{}).get('cursor')=='hold' for row in packets(log)):await asyncio.sleep(.01)
            await asyncio.wait_for(request_seen(),3)
            assert not (await asyncio.wait_for(call('list_mcp_resources',dict(cursor='independent')),3)).is_error
            abort.abort(RuntimeError('cancel resource'))
            assert (await asyncio.wait_for(held,3)).is_error
            assert any(row['packet'].get('method')=='notifications/cancelled' for row in packets(log))
        await await_callback_result(ctx.loader.update(entry.id,dict(disabled=True)))
        assert process.returncode is not None and not connection._resource_operations
        assert 'read_mcp_resource' not in [row['name'] for row in ctx.tools.schemas(lease.agent)]
        methods=[row['packet']['method'] for row in packets(log)]
        assert ('resources/list' in methods)==capabilities
        assert ('resources/templates/list' in methods)==capabilities
        (tmp_path/'mcp-resource-connection-observations.json').write_text(json.dumps(dict(capabilities=capabilities,listed=listed.value,templates=templates.value,read=read.value,instructions=instructions,packets=packets(log),processClosed=True),indent=2),encoding='utf-8')
    finally:
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_instruction_byte_limit_rejects_before_tool_discovery(tmp_path):
    log=tmp_path/'peer.jsonl';counter=tmp_path/'counter.txt'
    config=dict(transport='stdio',serverName='docs',command=sys.executable,
        args=[str(PEER),str(log),str(counter),'resources'],maxInstructionBytes=4,
        reconnect=dict(enabled=False),failOnStartupError=False)
    ctx=await setup(tmp_path,extra=[('mcp-resources',{}),('mcp-client',config)])
    try:
        entry=next(entry for entry in ctx.loader.entries() if entry.options.get('id')=='mcp-client')
        connection=entry.fiber.plugin.connection
        assert 'server instructions exceed maxInstructionBytes (4)' in str(connection.ready.result()['error'])
        assert connection.instructions()=='' and connection.client is None
        assert not any(row['packet']['method']=='tools/list' for row in packets(log))
        assert not connection._resource_operations
    finally:await ctx.fiber.dispose()


def packets(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


@pytest.mark.asyncio
async def test_resource_calls_and_instructions_follow_reconnected_generation(tmp_path):
    log=tmp_path/'peer.jsonl';counter=tmp_path/'counter.txt'
    config=dict(transport='stdio',serverName='docs',command=sys.executable,
        args=[str(PEER),str(log),str(counter),'resources'],
        reconnect=dict(enabled=True,initialDelayMs=10,maxDelayMs=20,maxAttempts=3),failOnStartupError=True)
    ctx=await setup(tmp_path,extra=[('mcp-resources',{}),('mcp-client',config)]);lease=None;held=None
    try:
        entry=next(entry for entry in ctx.loader.entries() if entry.options.get('id')=='mcp-client')
        connection=entry.fiber.plugin.connection;old=connection.client
        lease=await ctx.agents.create(dict(sessionId='owner',agentOptions=dict(provider='script',model='m')))
        async def call(cursor):
            return await ctx.tools.execute(ToolExecutionInput(cursor,'list_mcp_resources',dict(server='docs',cursor=cursor),agent=lease.agent,signal=NEVER_ABORTED))
        held=asyncio.create_task(call('hold'))
        async def seen():
            while not any(row['packet'].get('params',{}).get('cursor')=='hold' for row in packets(log)):await asyncio.sleep(.01)
        await asyncio.wait_for(seen(),3)
        stopped=await asyncio.wait_for(call('stop'),3)
        assert stopped.is_error and (await asyncio.wait_for(held,3)).is_error
        async def reconnected():
            while connection.client is None or connection.client is old or connection._connected_at is None:await asyncio.sleep(.01)
        await asyncio.wait_for(reconnected(),5)
        current=connection.client
        assert old.proc.returncode is not None and not old._pending
        result=await asyncio.wait_for(call('new'),3)
        assert not result.is_error and result.value['resources'][0]['description']=='generation 2'
        assert 'generation 2' in connection.instructions()
        assert not connection._resource_operations
        await await_callback_result(ctx.loader.update(entry.id,dict(disabled=True)))
        assert current.proc.returncode is not None and connection.instructions()==''
        (tmp_path/'mcp-resource-reconnect-observations.json').write_text(json.dumps(dict(value=result.value,packets=packets(log),oldPending=0,allProcessesClosed=True),indent=2),encoding='utf-8')
    finally:
        if held is not None:await asyncio.gather(held,return_exceptions=True)
        if lease is not None:await lease.dispose()
        await ctx.fiber.dispose()
