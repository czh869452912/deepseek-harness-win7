"""Pair actual original/Python MCP client resource calls through local stdio."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe
OUTPUT=None


async def observe():
    from types import SimpleNamespace as NS
    from dsh.cordis import Context
    from dsh.core.abort import NEVER_ABORTED
    from dsh.core.system_prompt.current import CurrentSystemPrompt
    from dsh.core.tools import CurrentToolsPlugin
    from dsh.core.tool_executor_native import NativeToolExecutorPlugin
    from dsh.mcp.resources_current import CurrentMcpResources
    from dsh.mcp.current import CurrentMcpClient
    rows=[]
    for capabilities in (True,False):
        ctx=Context();directory=OUTPUT/('native-'+str(capabilities).lower());directory.mkdir()
        log=directory/'peer.jsonl';counter=directory/'counter.txt'
        for plugin in (CurrentSystemPrompt,CurrentToolsPlugin,NativeToolExecutorPlugin,CurrentMcpResources):await ctx.plugin(plugin)
        try:
            fiber=await ctx.plugin(CurrentMcpClient,config=dict(transport='stdio',serverName='docs',command=sys.executable,
                args=[str(ROOT/'scripts/oracles/rc022_mcp_resource_peer.py'),str(log),str(counter),'resources' if capabilities else 'none'],reconnect=dict(enabled=False),failOnStartupError=True))
            values=[]
            for request in [dict(method='resources/list',cursor=''),dict(method='resources/templates/list'),dict(method='resources/read',uri='doc://a')]:
                values.append(await ctx.mcpResources._request('docs',request,NS(signal=NEVER_ABORTED,agent=None)))
            assembled=await ctx.systemPrompt.assemble();instructions=dict(next(row for row in assembled['sections'] if row['name']=='mcp:docs'))
            await fiber.dispose()
            methods=[json.loads(line)['packet'] for line in log.read_text(encoding='utf-8').splitlines()]
            requests=[{key:value for key,value in packet.items() if key in ('method','params')} for packet in methods if packet['method'].startswith('resources/')]
            rows.append(dict(capabilities=capabilities,values=values,instructions=instructions,requests=requests,toolsAfter=[row['name'] for row in ctx.tools.schemas()]))
        finally:await ctx.fiber.dispose()
    return rows


def prepare(output):
    global OUTPUT
    OUTPUT=output
    path=output/'input.json';path.write_text(json.dumps(dict(output=str(output),python=sys.executable,peer=str(ROOT/'scripts/oracles/rc022_mcp_resource_peer.py'))),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_resource_connection.mts','Actual original/Python client plugins over the same owned legacy stdio peer: resource capability guard, empty cursor, templates/read raw DTOs, literal attributed instructions, exact resource request params and unload visibility. Initialization/modern SDK negotiation and supervisor status are not normalized or compared by this resource-only observation.',[Path(__file__).resolve(),ROOT/'dsh/mcp/current.py',ROOT/'dsh/mcp/protocol.py',ROOT/'dsh/mcp/resource_schemas_current.json',ROOT/'scripts/oracles/rc022_mcp_resource_peer.py'],prepare=prepare)
