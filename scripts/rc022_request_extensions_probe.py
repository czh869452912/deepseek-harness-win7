"""Actual request-extension preparation/serialization/acceptance transitions."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


def cases():
    return [dict(mode=mode,fields=fields) for mode in ('normal','prepare-error','accept-error','merged-overflow','base-overflow','omit-reporter-error','accept-reporter-error')
        for fields in ({},{'inventory':{'rows':['a','b']}},{'model':'collision'},{'10':10,'2':2,'x':None},{'quote"\n':True},{'__proto__':{'value':1}})]


def prepare(output):
    path=output/'inputs.json';path.write_text(json.dumps(cases(),ensure_ascii=True),encoding='utf-8');return [path]


async def observe():
    from dsh.llm import deepseek_request_extensions as module
    from dsh.llm.error import error_chain
    from dsh.cordis.utils import _js_own_enumerable_keys
    original=module.stringify_json;rows=[]
    for index,case in enumerate(cases()):
        mode=case['mode'];events=[];requests=[];serial=[]
        body=dict(model='m',messages=[dict(role='user',content=[dict(type='text',text='hello')])])
        async def acceptance():
            events.append('accepted')
            if mode in ('accept-error','accept-reporter-error'):raise RuntimeError('commit unavailable')
        async def prepare_request(request):
            requests.append(dict(bodySame=request['body'] is body,sessionId=request['sessionId'],purpose=request['purpose']))
            if mode=='prepare-error':
                error=RuntimeError('prepare unavailable');error.cause=RuntimeError('inner failure');raise error
            return SimpleNamespace(fields=case['fields'],accept=acceptance)
        def stringify(value):
            if isinstance(value,dict) and 'messages' in value:
                serial.append(_js_own_enumerable_keys(value))
                if mode=='base-overflow' or mode in ('merged-overflow','omit-reporter-error') and any(key in value for key in case['fields']):
                    raise RuntimeError('synthetic serialization overflow')
            return original(value)
        def omitted(fields,error):
            events.append(dict(omitted=fields,error=error_chain(error)))
            if mode=='omit-reporter-error':raise RuntimeError('omission reporter failed')
        def unaccepted(error):
            events.append(dict(unaccepted=error_chain(error)))
            if mode=='accept-reporter-error':raise RuntimeError('acceptance reporter failed')
        module.stringify_json=stringify
        try:
            prepared=await module.prepareRequestExtensions(body,dict(sessionId='s',purpose='compaction'),prepare_request,omitted,unaccepted)
            before=list(events)
            result=dict(payload=prepared.payload,beforeAcceptance=before)
            try:await prepared.accept();result['acceptance']='fulfilled'
            except Exception as error:result['acceptanceError']=error_chain(error)
        except Exception as error:result=dict(error=error_chain(error),code=getattr(error,'code',None))
        finally:module.stringify_json=original
        rows.append(dict(index=index,requests=requests,serial=serial,events=events,**result))
    rows.extend(await registry_observe())
    return rows


async def registry_observe():
    from dsh.cordis.awaiting import await_callback_result
    from dsh.cordis.context import Context
    from dsh.core.abort import AbortController
    from dsh.llm.deepseek_api_extensions_current import CurrentDeepSeekLlmApiExtensions
    from dsh.llm.deepseek_request_extensions import prepareRequestExtensions
    from dsh.llm.error import error_chain
    ctx=Context();rows=[];commits=[];mode=[True];mutable={'value':0}
    try:
        await ctx.plugin(CurrentDeepSeekLlmApiExtensions)
        registry=ctx.deepseekLlmApiExtensions
        def bad(_):
            if mode[0]:raise RuntimeError('prepare unavailable')
            return dict(value=['recovered'])
        undo=registry.register('inventory_bad',dict(prepare=bad))
        registry.register('inventory_good',dict(prepare=lambda _:dict(value=mutable,accept=lambda:commits.append(True))))
        for round in range(5):
            if round==2:
                await await_callback_result(undo());undo=registry.register('inventory_bad',dict(prepare=bad))
            mode[0]=round!=3;mutable['value']=round
            request=await prepareRequestExtensions(dict(model='m'),dict(signal=AbortController().signal),registry.prepare,
                lambda *_:None,lambda *_:None)
            mutable['value']=99
            await request.accept();await request.accept()
            warnings=[dict(format=message.args[0],error=error_chain(message.args[1])) for message in ctx.logger.buffer if message.type=='warn']
            rows.append(dict(kind='registry',round=round,payload=request.payload,commits=len(commits),warnings=warnings))
        def fail(message):
            def commit():raise RuntimeError(message)
            return commit
        for field,message in [('fail_one','first commit'),('fail_two','second commit')]:
            registry.register(field,dict(prepare=lambda _,message=message:dict(value=True,accept=fail(message))))
        unaccepted=[]
        request=await prepareRequestExtensions(dict(model='m'),dict(signal=AbortController().signal),registry.prepare,
            lambda *_:None,lambda error:unaccepted.append(error_chain(error)))
        await request.accept();await request.accept()
        rows.append(dict(kind='aggregate',unaccepted=unaccepted,commits=len(commits)))
    finally:await ctx.fiber.dispose()
    return rows


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_request_extensions.mts','Actual Source request extensions: immutable base identity and request facts, base-field collision, integer-key order, preparation cause chain, merged serialization fallback, invalid base refusal, acceptance failure containment and reporter failures. Controlled serializer overflow matches upstream fault-injection tests.',
        [Path(__file__).resolve(),ROOT/'dsh/llm/deepseek_request_extensions.py'],prepare=prepare)
