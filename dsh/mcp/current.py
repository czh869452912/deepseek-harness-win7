"""Current MCP plugin with stable status and generation replacement ownership."""
import json
from pathlib import Path

from dsh.cordis.schema import Schema
from dsh.cordis.awaiting import start_coroutine
from dsh.core.scope import scope_of
from dsh.mcp.client import McpClientPlugin, _active_server_names
from dsh.mcp.connection import RECONNECT_ABSENT, resolve_reconnect_policy
from dsh.mcp.connection_current import SupervisedMcpConnection
from dsh.mcp.status_current import register_status_cell
from dsh.mcp.generation_current import _SharedCleanup
from dsh.mcp.config import CONFIG as PREVIOUS_CONFIG
from dsh.mcp.tools import sync_tools as previous_sync

RESOURCE_SCHEMAS=json.loads(Path(__file__).with_name('resource_schemas_current.json').read_text(encoding='utf-8'))

RESOURCE_CONFIG=Schema.union([Schema.object(dict(
    {key:value for key,value in branch.dict.items() if key not in ('failOnStartupError','reconnect')},
    startupTimeoutMs=Schema.number().min(1).max(2147483647),
    closeTimeoutMs=Schema.number().min(1).max(2147483647).default(5000),
    expandTemplates=Schema.boolean().default(False),
    failOnStartupError=branch.dict['failOnStartupError'],
    maxInstructionBytes=Schema.number().step(1).min(1).default(32768),
    reconnect=branch.dict['reconnect'])) for branch in PREVIOUS_CONFIG.list])


async def sync_tools(client, ctx, opts, previous):
    return await previous_sync(client, ctx, dict(opts, currentContract=True), previous)


class CurrentMcpConnection(SupervisedMcpConnection):
    pass


class CurrentMcpClient(McpClientPlugin):
    connection_class = CurrentMcpConnection
    Config=RESOURCE_CONFIG

    async def apply(self, ctx):
        server_name=self.config['serverName']
        policy=resolve_reconnect_policy(self.config.get('reconnect',RECONNECT_ABSENT),path='mcp-client('+server_name+'): reconnect')
        owner=scope_of(ctx)
        if owner is None:owner=ctx.root
        owner_id=id(owner)
        def warn(message,error):
            ctx.logger.warn('mcp-client('+server_name+'): '+message)
            if not self.config.get('expandTemplates'):ctx.logger.warn(error)
        def reserve():
            entry=_active_server_names.setdefault(owner_id,(owner,set()))
            names=entry[1]
            if server_name in names:
                raise ValueError('mcp-client: serverName "'+server_name+'" is already in use by another mcp-client instance — pick a unique serverName in cordis.yml')
            names.add(server_name)
            self.status=register_status_cell(ctx.fiber,warn)
            def release():
                if ctx.fiber.uid is None:self.status.detach()
                names.discard(server_name)
                if not names and _active_server_names.get(owner_id) is entry:_active_server_names.pop(owner_id,None)
            return release
        ctx.effect(reserve,label='mcp-client.serverName')
        closure=self.status.closure()
        if not closure['closeConfirmed'] or 'cleanupError' in closure:
            raise RuntimeError('mcp-client('+server_name+'): previous connection cleanup is incomplete; restart the Host')
        connection=self.connection=self.connection_class(ctx,self.config,policy,self.status)
        stopping=[None]
        def dispose():
            if stopping[0] is None:stopping[0]=_SharedCleanup(start_coroutine(connection.dispose()))
            return stopping[0]
        def unloading(fiber):
            if fiber is ctx.fiber and fiber.uid is None:return dispose()
        ctx.on('internal/plugin',unloading,global_listener=True)
        ctx.effect(lambda: dispose,label='mcp-client.connection')
        self.register_context(ctx,server_name,connection)
        outcome=await connection.ready
        if outcome.get('error') is not None and self.config.get('failOnStartupError'):
            raise RuntimeError('mcp-client('+server_name+'): initial connection or tool synchronization failed') from outcome['error']

    def register_context(self,ctx,server_name,connection):
        ctx.inject(['mcpResources'],lambda child:child.mcpResources.register(server_name,connection.resources))
        def instructions(child):
            child.systemPrompt.section(dict(name='mcp:'+server_name,order=child.systemPrompt.getSectionOrder('MCP_SERVERS'),
                interpolate=False,text=lambda *_:connection.instructions()))
        ctx.inject(['systemPrompt'],instructions)
