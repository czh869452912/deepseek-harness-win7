"""Generation-facing SDK client surface over the native current wire providers."""
from dsh.cordis.awaiting import await_callback_result
from dsh.cordis.json_text import stringify_json
from dsh.mcp.diagnostic_current import McpLocalError, CurrentProtocolError
from dsh.mcp.schemas import parse
from dsh.mcp.response_cache_current import CurrentResponseCache


class CurrentSdkClient:
    def __init__(self, name='dsh-mcp-client', input_required=None, default_cache_ttl_ms=0, list_max_pages=64):
        self.client_info = dict(name=name, version='0.0.1')
        self.transport = None
        self._wire = None
        self.onclose = None
        self.on_notification = None
        self.onerror = None
        self.input_required = dict(input_required or {})
        self._cache = CurrentResponseCache()
        self.default_cache_ttl_ms = default_cache_ttl_ms
        self.list_max_pages = list_max_pages
        self._output_validator = None

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
            if self._output_validator is not None:
                self._output_validator.close()
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
        try:
            if self._wire is not None:
                await self._wire.close()
        finally:
            self._cache.reset()
            if self._output_validator is not None:
                await self._output_validator.close()

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

    async def _list(self, method, key, params=None, options=None, finalize=None):
        if params is not None and 'cursor' in params:
            result = await self.request(dict(method=method, params=params), options)
            return finalize(result) if finalize is not None else result
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
        if finalize is not None:
            result = finalize(result)
        if (options or {}).get('cacheMode') != 'bypass':
            self._cache.write(method, '', result, generation, self._expires_at(result))
        return result

    async def listTools(self, params=None, options=None):
        return await self._list('tools/list', 'tools', params, options, self._filter_tools)

    def _modern(self):
        return self.transport is not None and (getattr(self.transport,'negotiated',None) or {}).get('era') == 'modern'

    def _filter_tools(self, result):
        if not self._modern() or getattr(self.transport,'transport_kind',None) == 'stdio':
            return result
        import logging
        from dsh.mcp.param_headers_current import scan_declarations
        tools = []
        for tool in result['tools']:
            scan = scan_declarations(tool.get('inputSchema'))
            if scan['valid']:tools.append(tool)
            else:logging.getLogger(__name__).warning("[mcp-sdk] excluding tool '%s' from tools/list: invalid x-mcp-header declaration — %s",tool['name'],scan['reason'])
        if len(tools) != len(result['tools']):result['tools'] = tools
        return result

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

    def _definition(self, name, options):
        definition = options.get('toolDefinition')
        if 'toolDefinition' not in options:
            entry = self._cache.entries.get(('tools/list', ''))
            if entry is not None:
                import json
                for tool in json.loads(entry['value'])['tools']:
                    if tool['name'] == name:
                        definition = tool
        return definition

    async def _compile_tool_output(self, name, options):
        definition = self._definition(name,options)
        from dsh.cordis.utils import _js_truthy as js_truthy
        schema = definition.get('outputSchema') if definition is not None else None
        if js_truthy(schema):
            if self._output_validator is None:
                from dsh.mcp.output_validator_current import CurrentOutputValidator
                self._output_validator = CurrentOutputValidator()
            compiled = await self._output_validator.observe(dict(schema=schema,compileOnly=True))
            if not compiled['compiled']:
                message = compiled['message'].encode('utf-16-le','surrogatepass')[:400].decode('utf-16-le','surrogatepass')
                raise CurrentProtocolError(-32602, "Tool '"+name+"' has an invalid outputSchema: "+message)
        return schema

    def _tool_send_options(self, params, options):
        if not self._modern():return options
        from dsh.mcp.param_headers_current import scan_declarations,build_param_headers
        definition = self._definition(params['name'],options)
        if definition is None:return options
        scan = scan_declarations(definition.get('inputSchema'))
        if not scan['valid']:return options
        headers = build_param_headers(scan['declarations'],params.get('arguments'))
        return dict(options,headers=dict(options.get('headers') or {},**headers)) if headers else options

    async def callTool(self, params, options=None):
        options = options or {}
        schema = await self._compile_tool_output(params['name'],options)
        try:
            result = await self.request(dict(method='tools/call',params=params),self._tool_send_options(params,options))
        except CurrentProtocolError as error:
            if not self._modern() or error.code != -32020 or 'toolDefinition' in options:raise
            self._cache.evict('tools/list')
            refresh = {key:options[key] for key in ('signal','timeout') if key in options}
            refresh['cacheMode'] = 'refresh'
            try:await self.listTools(options=refresh)
            except Exception as refresh_error:
                if self.onerror is not None:self.onerror(refresh_error)
            schema = await self._compile_tool_output(params['name'],options)
            result = await self.request(dict(method='tools/call',params=params),self._tool_send_options(params,options))
        from dsh.cordis.utils import _js_truthy as js_truthy
        if js_truthy(schema) and not js_truthy(result.get('isError')):
            if 'structuredContent' not in result:
                raise CurrentProtocolError(-32600, 'Tool '+params['name']+' has an output schema but did not return structured content')
            validation = await self._output_validator.observe(dict(schema=schema,value=result['structuredContent']))
            if not validation['valid']:
                raise CurrentProtocolError(-32602, "Structured content does not match the tool's output schema: "+validation['errorMessage'])
        return result
