"""Pair executor-owned capability lookup, refusal and cancellation identity."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.core.abort import AbortController
    from dsh.core.tools import ToolsService, ToolExecutionInput, ToolNotFoundError
    from dsh.core.tool_pipeline import ToolExecutionPipeline
    from dsh.llm.error import HarnessError
    from dsh.core.session.json import deep_freeze
    rows=[]
    for action in ('virtual','refuse','refuse-aborted','nested','disappeared','unknown','post-value',
                   'classifier','abort-reason','abort-name','abort-identity','abort-other'):
        ctx=Context();tools=ToolsService(ctx,contract_version=4);ctx.provide('tools',tools)
        controller=AbortController();primary=RuntimeError('cancel reason');trace=[];lookups=[];agent=object();admission=object()
        schema=deep_freeze(dict(name='private',description='bound',parameters={}))
        row=dict(action=action)
        def body(args,execution):
            trace.append('body');row['schemaSame']=execution.schema is schema
            if action.startswith('abort-'):
                controller.abort(primary)
                if action=='abort-reason':raise primary
                if action=='abort-identity':raise HarnessError('own failure','OWN_FAILURE')
                error=RuntimeError('operation failed')
                if action=='abort-name':error.name='AbortError'
                raise error
            return 'ok'
        definition=dict(name='private',description='private',parameters=dict(type='object'),
            output=dict(schema=dict(type='string'),render=lambda a,v:[dict(type='text',text=v)]),
            execute=body,isConcurrencySafe=lambda args:True,
            projectContent=lambda e,r:(trace.append('project') or [dict(type='text',text='prepared')]),
            finalizeContent=lambda e,r:(trace.append('final') or r.content))
        # Keep the private definition outside the registry under test.
        private_ctx=Context();private_tools=ToolsService(private_ctx)
        private_tools.register(definition);private=private_tools.get_tool('private')
        available=True
        def get(name,scope,tool_set):
            lookups.append(dict(name=name,agent=scope is agent,admission=tool_set is admission))
            return private if name=='private' and available else None
        def reject(name,nested):
            return ToolNotFoundError(name,'direct invocation forbidden') if not nested and action in ('refuse','refuse-aborted') else None
        pipeline=ToolExecutionPipeline(ctx,dict(get=get,reject=reject))
        async def pre(execution,next_fn):
            nonlocal available
            trace.append('pre')
            if action=='disappeared':available=False
            return await next_fn()
        async def post(execution,result,next_fn):
            trace.append('post')
            return dict(kind='accept',**(dict(value='replacement') if action=='post-value' else {}))
        ctx.on('tools/pre-execute',pre);ctx.on('tools/post-execute',post)
        ctx.on('tools/result',lambda e,r:trace.append('result'))
        if action=='refuse-aborted':controller.abort(primary)
        execution=ToolExecutionInput('call','absent' if action=='unknown' else 'private',
            42 if action=='classifier' else {},agent=agent,signal=controller.signal,toolSet=admission,
            schema=schema,parent=object() if action=='nested' else None)
        row['mode']=pipeline.execution_mode(execution)['kind']
        if action!='classifier':
            prepared=await pipeline.prepare(execution)
            outcome=await pipeline.dispatch(prepared['exec']) if prepared['kind']=='dispatch' else prepared
            result=await pipeline.complete(prepared['exec'],outcome)
            row.update(stage=prepared['kind'],isError=result.is_error,error=result.error if result.is_error else None,
                       content=result.content,value=result.value if not result.is_error else None)
        row.update(trace=trace,lookups=lookups,registry=tools.get_tool('private') is not None)
        rows.append(row);await ctx.fiber.dispose();await private_ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__=='__main__':
    probe.native=observe
    probe.main('rc022_pipeline_source.mts','Executor-private definitions, pre-policy refusal and cancellation precedence, shared staged completion, schema identity and unclassified cancellation.',
        [Path(__file__).resolve(),ROOT/'dsh/core/tools.py',ROOT/'dsh/core/tool_pipeline.py',ROOT/'dsh/core/tool_executor_native.py'])
