"""Exercise the selected PTC executor, private transport and runtime lifecycle."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe
ACTIONS = ('missing', 'unknown-language', 'python-schema', 'typescript-schema', 'repl-schema', 'controls-schema',
    'standalone', 'agent', 'direct', 'nested-error', 'admission', 'no-directory', 'description',
    'timeout-unavailable', 'timeout-invalid', 'escalation-unavailable', 'policy-missing',
    'program-error', 'runtime-timeout', 'caller-abort', 'retained-abort', 'limit',
    'reset-unsupported', 'reset', 'reset-fails', 'release-once', 'null')


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.service import Service
    from dsh.core.abort import AbortController
    from dsh.core.tools import CurrentToolsPlugin, _json_snapshot
    from dsh.core.system_prompt import SystemPrompt
    from dsh.core.tool_executor_ptc import PtcExecutor
    rows = []
    for action in ACTIONS:
        ctx = Context()
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(CurrentToolsPlugin)
        events, notices, releases, runs, bodies = [], [], [], [], []
        controller = AbortController()
        row = dict(action=action)
        agent = SimpleNamespace(ctx=ctx, session=SimpleNamespace(id='session', append=lambda kind,data: events.append(dict(type=kind, data=_json_snapshot(data)))))
        setattr(agent, 'inject', lambda message: notices.append(message['content'][0]['text']))
        if action != 'no-directory':
            ctx.set_service('workingDirectory', SimpleNamespace(ensure=lambda agent,signal: str(ROOT)))
        class Runtime(Service):
            language = 'typescript' if action in ('typescript-schema', 'repl-schema') else 'unknown' if action=='unknown-language' else 'python'
            programFormat = 'repl' if action=='repl-schema' else 'function-body'
            retainsState = action in ('retained-abort','reset','reset-fails')
            sandboxMode = 'read-only' if action in ('controls-schema','policy-missing') else None
            timeout = None if action=='timeout-unavailable' else dict(defaultMs=120000,maxMs=600000)
            executionInstructions = 'Provider instructions.'
            def __init__(self, ctx):
                super().__init__(ctx, 'ptcRuntime')
            def resolve(self, request):
                return dict(request, cwd=request.get('cwd', str(ROOT)), timeoutMs=1000 if action=='limit' else request.get('timeoutMs',120000))
            async def run(self, spec):
                functions = spec['bindings'][0]['functions']
                runs.append(dict(program=spec['program'], names=sorted(functions), cwd=spec['cwd'], timeout=spec['timeoutMs'],
                    stateOwner=spec.get('stateOwner') is agent, hasOwner='stateOwner' in spec))
                if action in ('caller-abort','retained-abort'):
                    controller.abort(RuntimeError('caller canceled'))
                    return dict(logs=[], error=dict(kind='abort', message='worker canceled'))
                if action in ('program-error','runtime-timeout'):
                    return dict(logs=['captured'], error=dict(kind='timeout' if action=='runtime-timeout' else 'exception', message='program failed'))
                if action=='null':
                    return dict(logs=[], value=None)
                try:
                    value = await functions['work'](dict(n=3))
                except Exception as error:
                    if action=='limit':
                        return dict(logs=[], error=dict(kind='abort', message='worker canceled'))
                    value = getattr(error, 'message', str(error))
                return dict(logs=['log'], value=value)
            async def release(self, owner):
                releases.append(owner is agent)
                if action=='reset-fails':
                    raise RuntimeError('release failed')
        if action!='missing':
            await ctx.plugin(Runtime)
        def body(args, execution):
            bodies.append(dict(schema=execution.schema['name'], parent=execution.parent is not None,
                admitted=execution.toolSet is not None, n=args['n']))
            if action=='nested-error':
                raise RuntimeError('nested failed')
            return dict(n=args['n']*2)
        ctx.tools.register(dict(name='work', description='Read work', parameters=dict(type='object',
            properties=dict(n=dict(type='integer')), required=['n']), execute=body,
            output=dict(schema=dict(type='object', properties=dict(n=dict(type='integer')), required=['n']),
                render=lambda args,value: [dict(type='text',text=str(value['n']))])))
        executor = PtcExecutor(ctx, dict(maxSubCallsPerMinute=1) if action=='limit' else {})
        ctx.tools.setExecutor(executor)
        selection = None
        try:
            if action in ('missing','unknown-language') or action.endswith('schema'):
                try:
                    row['model'] = executor.describe(ctx.tools.definitions())
                    row['sdk'] = executor.render_sdk(ctx.tools.definitions())
                    row['sections'] = [dict(name=s['name'], order=s['order'], interpolate=s['interpolate']) for s in executor.sections]
                except Exception as error:
                    row['error'] = getattr(error, 'message', str(error))
            elif action.startswith('reset'):
                try:
                    await executor.reset(agent)
                    row['reset'] = 'done'
                except Exception as error:
                    row['reset'] = dict(message=error.message, code=error.code)
            else:
                if action=='admission':
                    selection = await ctx.tools.resolve(dict(agent=agent,modelSelection={},signal=controller.signal))
                args = dict(code='fixture',description='Run fixture')
                if action=='description':
                    args['description']='  '
                if action in ('timeout-unavailable','timeout-invalid'):
                    args['timeoutMs']=20 if action=='timeout-unavailable' else 0
                if action=='escalation-unavailable':
                    args.update(sandbox_permissions='danger-full-access', justification='Need access')
                input = dict(calls=[dict(type='tool-call',id='outer',name='work' if action=='direct' else 'run_code',
                    arguments=json.dumps(dict(n=1) if action=='direct' else args))], signal=controller.signal)
                if action!='standalone':
                    input['agent']=agent
                if selection is not None:
                    input['toolSet']=selection
                outcomes = []
                for _ in range(2 if action=='release-once' else 1):
                    batch = await ctx.tools.execute(input)
                    result = batch['results'][0]['result']
                    outcomes.append(dict(isError=result.is_error, error=_json_snapshot(result.error), content=_json_snapshot(result.content),
                        value=None if result.is_error else _json_snapshot(result.value)))
                row['results'] = outcomes
            row.update(bodies=bodies, runs=runs, events=events, notices=notices)
        finally:
            if selection is not None:
                selection.dispose()
            await ctx.fiber.dispose()
        row['releases'] = releases
        rows.append(row)
    return json.loads(json.dumps(rows))


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_ptc_executor.mts', 'Selected PTC executor and actual tools batch pipeline: private run_code transport, runtime-dependent schema/SDK, controls, admission-bound nested calls, direct refusal, error/abort/limit classification, null completion, state reset and once-per-original-provider Agent release.',
        [Path(__file__).resolve(), ROOT/'dsh/core/tool_executor_ptc.py', ROOT/'dsh/core/ptc_dispatches.py'])
