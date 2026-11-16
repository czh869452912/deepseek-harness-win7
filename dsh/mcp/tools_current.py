"""Current SDK tool fetch/swap lifetime over the shared content projection."""
from dsh.mcp.content import extract_text
from dsh.mcp.diagnostic_current import McpLocalError, describe_error
from dsh.mcp.tools import sync_tools as bridge
from dsh.mcp.signals_current import combined_signals


class McpToolRegistrationError(McpLocalError):
    def __init__(self, cause):
        super().__init__('MCP tool registration failed')
        self.cause = cause


async def sync_tools(client, ctx, opts, previous, eligible=lambda: True):
    class Adapter:
        async def request(self, packet, signal=None, timeout=60000):
            if packet['method'] == 'tools/list':
                if 'tools' not in (client.getServerCapabilities() or {}):
                    return dict(tools=[])
                return await client.listTools(None,dict(cacheMode='refresh',signal=opts['signal']))
            try:
                async with combined_signals(signal,opts['signal']) as combined:
                    result = await client.callTool(packet['params'],dict(signal=combined,timeout=timeout))
                if result.get('isError') is True and opts.get('redact') is not None:
                    return dict(isError=True,content=[dict(type='text',text=opts['redact'](extract_text(result.get('content',[]),packet['params']['name'])))])
                return result
            except Exception as error:
                if opts.get('redact') is not None:
                    raise McpLocalError(opts['redact'](describe_error(error))) from None
                raise
    return await bridge(Adapter(),ctx,dict(opts,currentContract=True,eligible=eligible,
        registrationFailure='throw',registrationErrorFactory=McpToolRegistrationError),previous)
