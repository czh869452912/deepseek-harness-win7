"""Current resource/instruction consumers over the legacy transport supervisor."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from dsh.cordis.schema import Schema
from dsh.cordis.json_text import stringify_json
from dsh.host.http_proxy_policy import JS_SPACE
from dsh.mcp.client import McpClientPlugin
from dsh.mcp.connection import McpConnection
from dsh.mcp.config import CONFIG as PREVIOUS_CONFIG
from dsh.mcp.tools import sync_tools as previous_sync
from dsh.mcp.schemas import parse

RESOURCE_SCHEMAS=json.loads(Path(__file__).with_name('resource_schemas_current.json').read_text(encoding='utf-8'))

RESOURCE_CONFIG=Schema.union([Schema.object(dict(branch.dict,
    maxInstructionBytes=Schema.number().step(1).min(1).default(32768))) for branch in PREVIOUS_CONFIG.list])


async def sync_tools(client, ctx, opts, previous):
    return await previous_sync(client, ctx, dict(opts, currentContract=True), previous)


class CurrentMcpConnection(McpConnection):
    current_contract = True

    def _create_transport(self):
        from dsh.mcp.transport_current import create_current_transport
        return create_current_transport(self.config)

    def __init__(self,ctx,config,policy):
        self._instructions=''
        self._resource_operations=set()
        super().__init__(ctx,config,policy)
        self.resources=SimpleNamespace(request=self.request_resource)

    def instructions(self):return self._instructions

    def _instruction_text(self,generation):
        text=(getattr(generation,'server_instructions',None) or '').rstrip(JS_SPACE)
        instructions='### MCP server: '+self.config['serverName']+'\n\n'+text if text else ''
        maximum=self.config.get('maxInstructionBytes',32768)
        encoded=instructions.encode('utf-16-le','surrogatepass').decode('utf-16-le','replace').encode('utf-8')
        if len(encoded)>maximum:
            raise ValueError(self._label+': server instructions exceed maxInstructionBytes ('+str(maximum)+')')
        return instructions

    def _enqueue_sync(self,generation,startup=False):
        self._instruction_text(generation)
        return super()._enqueue_sync(generation,startup)

    async def _connect_generation(self,startup):
        await super()._connect_generation(startup)
        if self.client is not None and self._connected_at is not None:
            self._instructions=self._instruction_text(self.client)

    def _down(self,generation):
        if self._current(generation):self._instructions=''
        super()._down(generation)

    async def request_resource(self,request,execution):
        generation=self.client
        if generation is None or self._connected_at is None or self.disposed:
            raise RuntimeError(self._label+': server is disconnected')
        method=request['method']
        if method in ('resources/list','resources/templates/list'):
            if 'resources' not in (getattr(generation,'server_capabilities',None) or {}):
                return {'resources' if method=='resources/list' else 'resourceTemplates':[]}
            params=dict(cursor=request['cursor']) if 'cursor' in request else None
        elif method=='resources/read':params=dict(uri=request['uri'])
        else:raise ValueError('unsupported MCP resource method: '+method)
        packet=dict(method=method)
        if params is not None:packet['params']=params
        async def operation():
            schema={'resources/list':'ListResourcesResultSchema','resources/templates/list':'ListResourceTemplatesResultSchema','resources/read':'ReadResourceResultSchema'}[method]
            async def page(payload):
                return parse(schema,await generation.request(payload,signal=execution.signal,timeout=self.config.get('toolCallTimeoutMs',60000)),RESOURCE_SCHEMAS)
            result=await page(packet)
            if method=='resources/read' or 'cursor' in request:return result
            key='resources' if method=='resources/list' else 'resourceTemplates'
            cursor=result.get('nextCursor');previous=result;pages=1
            while cursor is not None:
                if pages>=64:raise RuntimeError(method+': exceeded listMaxPages (64); server pagination did not terminate')
                following=await page(dict(method=method,params=dict(cursor=cursor)))
                if following.get('nextCursor')==cursor and stringify_json(following[key])==stringify_json(previous[key]):break
                result[key].extend(following[key]);previous=following;cursor=following.get('nextCursor');pages+=1
            result.pop('nextCursor',None)
            return result
        task=asyncio.create_task(operation())
        self._resource_operations.add(task)
        try:return await task
        finally:self._resource_operations.discard(task)

    async def _dispose(self):
        self._instructions=''
        await super()._dispose()
        await asyncio.gather(*list(self._resource_operations),return_exceptions=True)


class CurrentMcpClient(McpClientPlugin):
    connection_class = CurrentMcpConnection
    Config=RESOURCE_CONFIG

    def register_context(self,ctx,server_name,connection):
        ctx.inject(['mcpResources'],lambda child:child.mcpResources.register(server_name,connection.resources))
        def instructions(child):
            child.systemPrompt.section(dict(name='mcp:'+server_name,order=child.systemPrompt.getSectionOrder('MCP_SERVERS'),
                interpolate=False,text=lambda *_:connection.instructions()))
        ctx.inject(['systemPrompt'],instructions)
