"""Observe content projection and policy settlement through the real pipeline."""
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.core.tools import ToolsService, ToolExecutionInput
    from dsh.core.abort import AbortController
    rows = []
    for action in ('project', 'replace', 'project-fails', 'body-fails', 'pre-fails',
                   'post-fails', 'final-fails', 'guard-info', 'deny-info', 'cancel',
                   'arguments', 'nested-meta', 'unload'):
        ctx = Context()
        tools = ToolsService(ctx, contract_version=4)
        controller = AbortController()
        trace, observed = [], []
        row = dict(action=action)
        def text(value):
            return [dict(type='text', text=value)]
        def project(execution, result):
            trace.append('project')
            if action == 'project-fails':
                raise RuntimeError('projection failed')
            return text('prepared')
        def finalize(execution, result):
            trace.append('final')
            if action == 'final-fails':
                raise RuntimeError('finalization failed')
            return text('final:' + result.content[0]['text'])
        def execute(args, execution):
            trace.append('body')
            if action == 'body-fails':
                raise RuntimeError('body failed')
            return args['value']
        definition = dict(name='echo', description='echo', parameters=dict(type='object'),
            output=dict(schema=dict(type='string'), render=lambda a,v: text('fallback'),
                        presentationMeta=lambda a,v: dict(shown=v)),
            execute=execute, projectContent=project, finalizeContent=finalize)
        dispose = tools.register(definition)
        async def pre(execution, next_fn):
            trace.append('pre')
            tools.get_tool('echo').project_content = lambda e,r: text('late')
            if action == 'pre-fails':
                raise RuntimeError('pre failed')
            if action == 'unload':
                dispose()
            if action == 'deny-info':
                return dict(kind='deny', reason='blocked', info=dict(name='PolicyError', code='POLICY', reason='raw'))
            if action == 'cancel':
                return dict(kind='cancel')
            if action == 'arguments':
                return dict(kind='allow', arguments=dict(value='rewritten'))
            return await next_fn()
        async def post(execution, result, next_fn):
            trace.append('post:' + result.content[0]['text'])
            if action == 'post-fails':
                raise RuntimeError('post failed')
            return dict(kind='accept', **(dict(content=text('policy')) if action == 'replace' else {}))
        def result_observer(execution, result):
            trace.append('result')
            observed.append(result)
            try:
                execution.signal = controller.signal
                row['executionFrozen'] = False
            except AttributeError:
                row['executionFrozen'] = True
        ctx.on('tools/pre-execute', pre)
        ctx.on('tools/post-execute', post)
        ctx.on('tools/result', result_observer)
        if action == 'guard-info':
            tools.guard(lambda e: dict(reason='guarded', info=dict(name='GuardError', code='GUARD', reason='raw')))
        result = await tools.execute(ToolExecutionInput('call', 'echo', dict(value='original'),
            signal=controller.signal, parent=object() if action == 'nested-meta' else None))
        row.update(trace=trace, content=result.content, error=result.error if result.is_error else None,
                   value=result.value if not result.is_error else None, meta=result.meta,
                   exactResult=len(observed) == 1 and observed[0] is result,
                   schemaPrivate=not any(k in tools.schemas()[0] for k in ('projectContent','finalizeContent')) if action != 'unload' else True)
        rows.append(row)
        await ctx.fiber.dispose()
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_tool_pipeline.mts', 'Captured projectContent before post policy, finalization on every failure path, structured guards, cancellation, immutable arguments and nested metadata.',
               [Path(__file__).resolve(), ROOT/'dsh/core/tools.py'])
