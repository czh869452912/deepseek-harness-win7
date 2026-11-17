"""Generation-facing SDK client surface over the native current wire providers."""
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.mcp.diagnostic_current import McpLocalError
from dsh.mcp.schemas import parse
from dsh.mcp.response_cache_current import CurrentResponseCache


class CurrentSdkClient:
    def __init__(self, name='dsh-mcp-client', input_required=None, default_cache_ttl_ms=0, list_max_pages=64):
        self.client_info = dict(name=name, version='0.0.1')
        self.transport = None
        self._wire = None
        self.onclose = None
        self.on_notification = None
        self.input_required = dict(input_required or {})
        self._cache = CurrentResponseCache()
        self.default_cache_ttl_ms = default_cache_ttl_ms
        self.list_max_pages = list_max_pages

    async def connect(self, transport, options=None):
        if self._wire is not None:
            raise McpLocalError('MCP client can only be connected once')
        self._wire = self.transport = transport
        transport.client_info = self.client_info
        transport.input_required = self.input_required
        previous = transport.on_close

        def closed():
            self.transport = None
            self._cache.reset()
            if previous is not None:
                previous()
            if self.onclose is not None:
                return self.onclose()

        transport.on_close = closed
        transport.on_notification = self._notification
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

    def _notification(self, packet):
        self._cache.notification(packet)
        if self.on_notification is not None:
            return self.on_notification(packet)

    def _expires_at(self, result):
        ttl = result.get('ttlMs', self.default_cache_ttl_ms)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)):
            ttl = self.default_cache_ttl_ms
        # NaN remains stale, as in Math.min/Math.max in the SDK.
        bounded = ttl if ttl != ttl else min(max(0, ttl), 86400000)
        return self._cache.now() + bounded

    def _cached(self, method, params, options):
        if (options or {}).get('cacheMode') in ('refresh', 'bypass'):
            return None
        result = self._cache.read(method, params)
        signal = (options or {}).get('signal')
        if result is not None and signal is not None and signal.aborted:
            from dsh.mcp.negotiation_current import SdkError
            from dsh.cordis.utils import js_to_string
            reason = signal.reason
            raise reason if isinstance(reason, SdkError) else SdkError('REQUEST_TIMEOUT', js_to_string(reason))
        return result

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
        from dsh.mcp.negotiated_protocol_current import NegotiatedProtocol
        extra = dict(request_options=options) if isinstance(self.transport, NegotiatedProtocol) else {}
        value = await await_callback_result(self.transport.request(packet,
            signal=options.get('signal', signal), timeout=options.get('timeout', timeout), **extra))
        if options.get('allowInputRequired') and value.get('resultType') == 'input_required':
            return value
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
        hit = self._cached(method, '', options)
        if hit is not None:
            return hit
        generation = self._cache.capture(method)
        packet = dict(method=method)
        if params is not None:
            packet['params'] = params
        result = await self.request(packet, options)
        cursor, previous, pages = result.get('nextCursor'), result, 1
        # Own the assembled list without mutating a cached/raw first page.
        result = dict(result, **{key:list(result[key])})
        while cursor is not None:
            if self.list_max_pages != 0 and pages >= self.list_max_pages:
                from dsh.mcp.negotiation_current import SdkError
                raise SdkError('LIST_PAGINATION_EXCEEDED', method+': exceeded listMaxPages ('+str(self.list_max_pages)+'); server pagination did not terminate', dict(method=method,listMaxPages=self.list_max_pages))
            following = await self.request(dict(method=method, params=dict(params or {}, cursor=cursor)), options)
            if following.get('nextCursor') == cursor and stringify_json(following[key]) == stringify_json(previous[key]):
                break
            result[key].extend(following[key])
            previous, cursor, pages = following, following.get('nextCursor'), pages+1
        result.pop('nextCursor', None)
        if (options or {}).get('cacheMode') != 'bypass':
            self._cache.write(method, '', result, generation, self._expires_at(result))
        return result

    async def listTools(self, params=None, options=None):
        return await self._list('tools/list', 'tools', params, options)

    async def listResources(self, params=None, options=None):
        return await self._list('resources/list', 'resources', params, options)

    async def listResourceTemplates(self, params=None, options=None):
        return await self._list('resources/templates/list', 'resourceTemplates', params, options)

    async def readResource(self, params, options=None):
        method, uri = 'resources/read', params['uri']
        hit = self._cached(method, uri, options)
        if hit is not None:
            return hit
        generation = self._cache.capture(method, uri)
        result = await self.request(dict(method=method, params=params), options)
        if (options or {}).get('cacheMode') != 'bypass':
            expires_at = self._expires_at(result)
            if expires_at > self._cache.now():
                self._cache.write(method, uri, result, generation, expires_at)
            elif (options or {}).get('cacheMode') == 'refresh':
                self._cache.evict(method, uri)
        return result

    async def callTool(self, params, options=None):
        return await self.request(dict(method='tools/call', params=params), options)
