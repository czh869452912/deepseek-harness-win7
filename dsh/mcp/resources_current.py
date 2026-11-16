"""Scoped MCP resource providers and parallel-safe shared resource tools."""
from dsh.cordis.json_text import stringify_json
from dsh.cordis.service import Service
from dsh.core.scope import NamedEntries, ScopedLayers, create_scope, scope_of
from dsh.typert.stores import field


def render_resource_result(server, value):
    def project(item):
        if isinstance(item, list):return [project(row) for row in item]
        if isinstance(item, dict):
            return {key:('[binary resource: '+str(len(entry.encode('utf-16-le','surrogatepass'))//2)+' base64 characters; available to programmatic callers]'
                if key=='blob' and isinstance(entry,str) else project(entry)) for key,entry in item.items()}
        return item
    return [dict(type='text',text='MCP server: '+server+'\n'+stringify_json(project(value)))]


class ResourceLayer:
    def __init__(self):
        self.servers=NamedEntries(lambda name:ValueError('MCP resource server "'+name+'" is already registered in this scope'))
        self.dispose_tools=None

    def is_empty(self):return self.servers.is_empty()


class CurrentMcpResources(Service):
    inject=['tools']

    def __init__(self,ctx,config=None):
        super().__init__(ctx,'mcpResources')
        self.layers=ScopedLayers(lambda *_:ResourceLayer(),lambda:None)
        self._self_ctx=ctx
        def prompt(child):
            def text(context):
                names=sorted(self.layers.merge(field(context,'scope'),lambda layer:layer.servers),key=lambda name:name.encode('utf-16-be','surrogatepass'))
                return '' if not names else ('## MCP resource servers\n\nUse list_mcp_resources, list_mcp_resource_templates, or read_mcp_resource with one of these names '
                    +'as the server argument: '+stringify_json(names)+'.')
            child.systemPrompt.section(dict(name='mcp-resource-servers',order=child.systemPrompt.getSectionOrder('MCP_SERVERS'),interpolate=False,text=text))
        ctx.inject(['systemPrompt'],prompt)

    def register(self,server,provider):
        ctx=self.ctx;scope=scope_of(ctx);pending=[None]
        def own():
            yield lambda:pending[0]
            def insert(layer):
                first=layer.servers.is_empty();remove=layer.servers.insert(server,provider)
                try:
                    if first:layer.dispose_tools=self._register_tools(scope)
                except Exception:
                    remove();raise
                def undo():
                    remove()
                    if layer.servers.is_empty():pending[0]=layer.dispose_tools()
                return undo
            yield self.layers.effect(ctx,insert,dict(label='mcpResources.provider('+server+')'))
        return ctx.effect(own,'mcpResources.register('+server+')')

    def _register_tools(self,scope):
        ctx=self._self_ctx
        def own():
            tool_ctx=ctx
            if scope is not None:
                owned=create_scope(ctx,scope);yield owned.raw_dispose;tool_ctx=owned.ctx
            yield register_resource_tools(tool_ctx,self._request)
        return ctx.effect(own,'mcpResources.tools')

    async def _request(self,server,request,execution):
        provider=self.layers.merge(field(execution,'agent'),lambda layer:layer.servers).get(server)
        if provider is None:raise ValueError('MCP resource server "'+server+'" is unavailable in this agent\'s scope')
        return await field(provider,'request')(request,execution)


def register_resource_tools(ctx,request):
    server=dict(type='string',required=True,description='Configured MCP server name.')
    lists=dict(server=server,cursor=dict(type='string',description='Continuation cursor returned by this server.'))
    output=dict(schema={},render=lambda args,value,*_:render_resource_result(args['server'],value))
    specifications=[('list_mcp_resources','List resources available from an MCP server.','resources/list',lists),
        ('list_mcp_resource_templates','List parameterized resource URI templates from an MCP server.','resources/templates/list',lists),
        ('read_mcp_resource','Read an MCP resource by URI from the named server. Use a listed URI or an expanded resource template.','resources/read',
            dict(server=server,uri=dict(type='string',required=True,description='Resource URI to read.')))]
    def own():
        for name,description,method,parameters in specifications:
            async def execute(args,execution,method=method):
                payload=dict(method=method)
                key='uri' if method=='resources/read' else 'cursor'
                if key in args:payload[key]=args[key]
                return await request(args['server'],payload,execution)
            schema=dict(type='object',
                properties={key:{k:v for k,v in value.items() if k!='required'} for key,value in parameters.items()},
                required=[key for key,value in parameters.items() if value.get('required')])
            yield ctx.tools.register(dict(name=name,description=description,parameters=schema,output=output,
                isConcurrencySafe=lambda *_:True,execute=execute))
    return ctx.effect(own,'mcpResources.resourceTools')
