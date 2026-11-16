"""Generation-facing SDK client surface over the native current wire providers."""
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.mcp.diagnostic_current import McpLocalError
from dsh.mcp.schemas import parse


class CurrentSdkClient:
    def __init__(self, name='dsh-mcp-client'):
        self.client_info = dict(name=name, version='0.0.1')
        self.transport = None
        self._wire = None
        self.onclose = None
        self.on_notification = None

    async def connect(self, transport, options=None):
        if self._wire is not None:
            raise McpLocalError('MCP client can only be connected once')
        self._wire = self.transport = transport
        transport.client_info = self.client_info
        previous = transport.on_close

        def closed():
            self.transport = None
            if previous is not None:
                previous()
            if self.onclose is not None:
                return self.onclose()

        transport.on_close = closed
        transport.on_notification = lambda packet: self.on_notification(packet) if self.on_notification is not None else None
        options = options or {}
        signal = options.get('signal')
        if signal is not None:
            signal.throw_if_aborted()
        await transport.connect()
        if signal is not None:
            signal.throw_if_aborted()

    async def close(self):
        if self._wire is not None:
            await self._wire.close()

    def getServerVersion(self):
        return getattr(self._wire, 'server_info', None)

    def getServerCapabilities(self):
        return getattr(self._wire, 'server_capabilities', None)

    def getInstructions(self):
        return getattr(self._wire, 'server_instructions', None)

    async def request(self, packet, options=None, signal=None, timeout=60000):
        if self.transport is None:
            raise McpLocalError('Not connected')
        options = options or {}
        value = await await_callback_result(self.transport.request(packet,
            signal=options.get('signal', signal), timeout=options.get('timeout', timeout)))
        # Modern dispatch has already validated its revision-specific result.
        # Legacy resources use the pinned SDK schemas as well.
        if packet['method'].startswith('resources/'):
            from dsh.mcp.current import RESOURCE_SCHEMAS
            schema = {'resources/list':'ListResourcesResultSchema',
                'resources/templates/list':'ListResourceTemplatesResultSchema',
                'resources/read':'ReadResourceResultSchema'}[packet['method']]
            value = parse(schema, value, RESOURCE_SCHEMAS)
        return value

    async def _list(self, method, key, params=None, options=None):
        if params is not None and 'cursor' in params:
            return await self.request(dict(method=method, params=params), options)
        packet = dict(method=method)
        if params is not None:
            packet['params'] = params
        result = await self.request(packet, options)
        cursor, previous, pages = result.get('nextCursor'), result, 1
        # Own the assembled list without mutating a cached/raw first page.
        result = dict(result, **{key:list(result[key])})
        while cursor is not None:
            if pages >= 64:
                raise McpLocalError(method+': exceeded listMaxPages (64); server pagination did not terminate')
            following = await self.request(dict(method=method, params=dict(cursor=cursor)), options)
            if following.get('nextCursor') == cursor and stringify_json(following[key]) == stringify_json(previous[key]):
                break
            result[key].extend(following[key])
            previous, cursor, pages = following, following.get('nextCursor'), pages+1
        result.pop('nextCursor', None)
        return result

    async def listTools(self, params=None, options=None):
        return await self._list('tools/list', 'tools', params, options)

    async def listResources(self, params=None, options=None):
        return await self._list('resources/list', 'resources', params, options)

    async def listResourceTemplates(self, params=None, options=None):
        return await self._list('resources/templates/list', 'resourceTemplates', params, options)

    async def readResource(self, params, options=None):
        return await self.request(dict(method='resources/read', params=params), options)

    async def callTool(self, params, options=None):
        return await self.request(dict(method='tools/call', params=params), options)
