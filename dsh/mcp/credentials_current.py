"""Runtime MCP credential bindings and redaction across instance rotations."""
import asyncio
from urllib.parse import quote

from dsh.cordis.awaiting import await_callback_result,start_coroutine
from dsh.cordis.utils import _js_own_enumerable_keys
from dsh.mcp.diagnostic_current import McpLocalError,describe_error,redact_secrets
from dsh.mcp.templates_current import assert_template_syntax,credential_refs_in,resolve_template_string


def _encode_component(value):
    try:
        normalized = value.encode('utf-16-le','surrogatepass').decode('utf-16-le','strict')
    except UnicodeDecodeError:
        error = McpLocalError('URI malformed')
        error.name = 'URIError'
        raise error from None
    return quote(normalized,safe="-_.!~*'()",encoding='utf-8',errors='strict')


class McpTemplateBinding:
    def __init__(self, ctx, config):
        self.ctx, self.config = ctx, config
        self._secrets = {}
        record = config.get('env',{}) if config['transport']=='stdio' else config.get('headers',{})
        strings = [config.get('command',''),*config.get('args',[]),*[record[key] for key in _js_own_enumerable_keys(record)],config.get('cwd','')] if config['transport']=='stdio' else [config['url'],*[record[key] for key in _js_own_enumerable_keys(record)]]
        self.refs = dict.fromkeys(ref for value in strings for ref in credential_refs_in(value)).keys() if config.get('expandTemplates',False) else {}.keys()
        if config.get('expandTemplates',False):
            for value in strings:
                assert_template_syntax(value,'mcp-client('+config['serverName']+')')
            if self.refs and ctx.get('credentials') is None:
                raise McpLocalError('MCP credential templates require a credentials provider')

    def redact(self, text):
        return redact_secrets(text,self._secrets)

    def diagnostic(self, error, operation):
        if not self.config.get('expandTemplates',False):
            return describe_error(error)
        return 'mcp-client('+self.config['serverName']+'): '+operation+': '+self.redact(describe_error(error))

    async def resolve(self, signal):
        signal.throw_if_aborted()
        if not self.config.get('expandTemplates',False):
            return self.config
        values = {}

        async def credential(ref):
            if ref not in values:
                provider = self.ctx.get('credentials')
                if provider is None:
                    raise McpLocalError('MCP credential templates require a credentials provider')

                async def lookup():
                    result = await await_callback_result(provider.resolve(ref))
                    value = result.get('value') if isinstance(result,dict) else getattr(result,'value',None)
                    if value is not None and value!='':
                        self._secrets[value] = None
                        self._secrets[_encode_component(value)] = None
                    return value

                values[ref] = start_coroutine(lookup())
                def observed(completed):
                    if not completed.cancelled():
                        completed.exception()
                values[ref].add_done_callback(observed)
            return await asyncio.shield(values[ref])

        async def resolve(value, path):
            result = await resolve_template_string(value,path,credential)
            signal.throw_if_aborted()
            return result

        async def record(value, path):
            result = {}
            for key in _js_own_enumerable_keys(value):
                result[key] = await resolve(value[key],path+'.'+key)
            return result

        config = self.config
        if config['transport']=='stdio':
            args = []
            for index, arg in enumerate(config.get('args',[])):
                args.append(await resolve(arg,'args['+str(index)+']'))
            return dict(config,command=await resolve(config['command'],'command'),args=args,
                env=await record(config.get('env',{}),'env'),cwd=await resolve(config.get('cwd',''),'cwd'))
        return dict(config,url=await resolve(config['url'],'url'),headers=await record(config.get('headers',{}),'headers'))
