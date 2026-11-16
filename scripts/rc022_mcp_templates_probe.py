"""Pair credential grammar, per-attempt resolution and retained redaction."""
import asyncio
import copy
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def inputs():
    stdio=dict(transport='stdio',serverName='fixture',command='${credential:A}',args=['${credential:B}','${credential:A}:${credential:A}'],env={'10':'${credential:C}','2':'${credential:B}','__proto__':'${credential:A}'},cwd='${credential:C}',expandTemplates=True)
    http=dict(transport='streamable-http',serverName='fixture',url='http://${credential:A}/path',headers={'Authorization':'Bearer ${credential:B}','X':'${credential:A}'},expandTemplates=True)
    values=dict(A='abc',B='bcd',C='secret /\u6587')
    return dict(strings=['plain','${credential:A}','${credential:A}:${credential:A}','${credential:EMPTY}','${credential:MISSING}','${credential:1BAD}','${environment:A}','${x${credential:A}','${credential:A','${credential:_x}','${credential:A}\n${credential:B}','${credential:A-B}','${}','${credential:}','${credential:A}${credential:B}'],
        values=dict(values,EMPTY='',_x='underscore'),redact='abc bcd secret /\u6587 secret%20%2F%E6%96%87 rotated rotated%20%2F',
        bindings=[dict(name='stdio-order-memo-rotation',provider=True,config=stdio,attempts=[dict(values=values),dict(values=dict(values,A='rotated /',B='bcd'))]),
            dict(name='http-provider-lifetime',provider=True,config=http,attempts=[dict(values=values,removeProvider=True),dict(values=values,restoreProvider=True)]),
            dict(name='missing-then-present',provider=True,config=http,attempts=[dict(values={'A':'abc'}),dict(values=values)]),
            dict(name='aborted-resolution',provider=True,config=http,attempts=[dict(values=values,abortOn='A'),dict(values=values,aborted=True)]),
            dict(name='empty-credential',provider=True,config=dict(http,url='${credential:EMPTY}',headers={}),attempts=[dict(values={'EMPTY':''})]),
            dict(name='unpaired-surrogate',provider=True,config=dict(http,url='${credential:A}',headers={}),attempts=[dict(values={'A':'\ud800'})]),
            dict(name='no-provider',provider=False,config=http,attempts=[]),
            dict(name='malformed',provider=True,config=dict(http,url='${x${credential:A}'),attempts=[]),
            dict(name='disabled-raw',provider=False,config=dict(http,expandTemplates=False,url='${environment:A}'),attempts=[dict(values=values)]),
            dict(name='literal-no-provider',provider=False,config=dict(http,url='http://literal',headers={}),attempts=[dict(values={})])])


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.mcp.templates_current import assert_template_syntax,credential_refs_in,resolve_template_string,MissingTemplateValue
    from dsh.mcp.credentials_current import McpTemplateBinding
    from dsh.mcp.diagnostic_current import describe_error
    data=inputs();rows=[]
    for text in data['strings']:
        try:assert_template_syntax(text,'fixture');syntax=dict(ok=True)
        except Exception as error:syntax=dict(error=describe_error(error))
        calls=[]
        async def credential(ref):calls.append(ref);return data['values'].get(ref)
        try:resolved=dict(value=await resolve_template_string(text,'fixture',credential))
        except Exception as error:resolved=dict(error=describe_error(error),missing=isinstance(error,MissingTemplateValue))
        rows.append(dict(kind='string',refs=credential_refs_in(text),syntax=syntax,resolved=resolved,calls=calls))
    for spec in data['bindings']:
        ctx=Context();calls=[];attempt=None;controller=None
        class Provider:
            async def resolve(self,ref):
                calls.append(ref)
                if attempt.get('abortOn')==ref:controller.abort(RuntimeError('cancel resolution'))
                await asyncio.sleep(0)
                return dict(value=attempt['values'][ref],source='fixture') if ref in attempt['values'] else None
        provider=Provider()
        if spec['provider']:ctx.set_service('credentials',provider)
        row=dict(kind='binding',name=spec['name'])
        try:
            binding=McpTemplateBinding(ctx,spec['config']);row['refs']=list(binding.refs);row['attempts']=[]
            for attempt in spec['attempts']:
                controller=AbortController()
                if attempt.get('aborted'):controller.abort(RuntimeError('abort before'))
                if attempt.get('removeProvider'):ctx.set_service('credentials',None)
                if attempt.get('restoreProvider'):ctx.set_service('credentials',provider)
                before=len(calls)
                try:
                    resolved=await binding.resolve(controller.signal);result=dict(config=resolved,sameRaw=resolved is spec['config'])
                except Exception as error:result=dict(error=describe_error(error),missing=isinstance(error,MissingTemplateValue))
                row['attempts'].append(dict(result=result,calls=calls[before:],redacted=binding.redact(data['redact']),diagnostic=binding.diagnostic(RuntimeError(data['redact']),'connect')))
        except Exception as error:row['error']=describe_error(error)
        finally:await ctx.fiber.dispose()
        rows.append(row)
    return rows


def prepare(output):
    path=output/'input.json';path.write_text(json.dumps(inputs()),encoding='utf-8');return [path]


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_mcp_templates.mts','Original template grammar and binding, static reference order, per-attempt memoization and args-before-command resolution, provider removal/restoration, missing/empty credentials, abort checks, URI encoding failure and instance-lifetime rotation redaction. Uses only controlled synthetic values; supervisor integration remains separate.',[Path(__file__).resolve(),ROOT/'dsh/mcp/templates_current.py',ROOT/'dsh/mcp/credentials_current.py',ROOT/'dsh/mcp/diagnostic_current.py'],prepare=prepare)
