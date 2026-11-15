"""Pair step admission against the fixed upstream registry and pipeline."""
import asyncio
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
    for action in ('enabled', 'disabled', 'once', 'closed', 'foreign', 'removed',
                   'replace', 'reject', 'abort-before', 'abort-after', 'abort-reject', 'dispatch'):
        ctx = Context()
        tools = ToolsService(ctx)
        agent, foreign = object(), object()
        controller = AbortController()
        reason = RuntimeError('cancelled')
        failure = RuntimeError('condition failed')
        trace = []
        model = dict(provider='p', model='m', reasoningEffort='high')
        context = dict(agent=agent, modelSelection=model, signal=controller.signal)
        row = dict(action=action)
        async def condition(value):
            trace.append(dict(agent=value['agent'] is agent, model=value['modelSelection'] is model,
                              signal=value['signal'] is controller.signal))
            await asyncio.sleep(0)
            if action in ('abort-after', 'abort-reject'):
                controller.abort(reason)
            if action in ('reject', 'abort-reject'):
                raise failure
            if action in ('removed', 'replace'):
                dispose()
            if action == 'replace':
                tools.register_canonical(definition, dict(when=condition))
            return action != 'disabled'
        bodies = []
        async def execute(args, execution):
            bodies.append(execution.toolSet is selection)
            return 'ok'
        definition = dict(name='echo', description='echo', parameters=dict(type='object'),
                          output=dict(schema=dict(type='string'), render=lambda args, value: [dict(type='text', text=value)]),
                          execute=execute)
        dispose = tools.register(definition, dict(when=condition))
        tools.register(dict(definition, name='plain'))
        row['inspect'] = [item.name for item in tools.definitions(agent)]
        row['outside'] = tools.executable('echo', agent) is not None
        if action == 'abort-before':
            controller.abort(reason)
        try:
            selection = await tools.resolve(context)
            if action == 'once':
                controller.abort(reason)
            if action == 'closed':
                selection.dispose()
                selection.dispose()
            scope = foreign if action == 'foreign' else agent
            row['admitted'] = [item.name for item in tools.definitions(scope, selection)]
            row['schemas'] = [item['name'] for item in tools.schemas(scope, selection)]
            row['executable'] = tools.executable('echo', scope, selection) is not None
            if action == 'dispatch':
                a = await tools.execute(ToolExecutionInput('a', 'echo', {}, agent=agent, signal=controller.signal))
                b = await tools.execute(ToolExecutionInput('b', 'echo', {}, agent=agent, signal=controller.signal, toolSet=selection))
                selection.dispose()
                c = await tools.execute(ToolExecutionInput('c', 'echo', {}, agent=agent, signal=controller.signal, toolSet=selection))
                row['results'] = [result.error['info']['code'] if result.is_error else result.value for result in (a,b,c)]
                row['bodies'] = bodies
            selection.dispose()
            row['disposed'] = len(selection.view(agent))
        except Exception as error:
            row['error'] = dict(name=type(error).__name__, message=getattr(error, 'message', str(error)),
                                code=getattr(error, 'code', None), cause=getattr(error, 'cause', None) is failure,
                                reason=error is reason)
            # RuntimeError is the native carrier for the same cancellation Error.
            if error is reason:
                row['error']['name'] = 'Error'
        row['conditions'] = trace
        rows.append(row)
        await ctx.fiber.dispose()
    from dsh.core.scope import create_scope
    for action in ('scoped-shadow', 'late-restriction', 'scoped-unload'):
        ctx = Context()
        tools = ToolsService(ctx)
        ctx.provide('tools', tools)
        class Agent:
            pass
        agent = Agent()
        scope = create_scope(ctx, agent)
        agent.ctx = scope.ctx
        controller = AbortController()
        definition = dict(name='echo', description='global', parameters=dict(type='object'),
                          output=dict(schema=dict(type='string'), render=lambda a,v: []), execute=lambda a,e: 'ok')
        tools.register(definition)
        if action != 'late-restriction':
            scope.ctx.tools.register(dict(definition, description='scoped'), dict(when=lambda value: action != 'scoped-shadow'))
        selection = await tools.resolve(dict(agent=agent, modelSelection={}, signal=controller.signal))
        row = dict(action=action, before=[item.description for item in tools.definitions(agent, selection)])
        if action == 'late-restriction':
            lift = scope.ctx.tools.restrict(dict(deny=['echo']))
        elif action == 'scoped-unload':
            await scope.dispose()
        row['after'] = [item.description for item in tools.definitions(agent, selection)]
        if action == 'late-restriction':
            lift()
            row['restored'] = [item.description for item in tools.definitions(agent, selection)]
        selection.dispose()
        rows.append(row)
        await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_tool_admission.mts', 'Step-time conditional admission, registration identity, closed/foreign scopes, cancellation precedence and actual pipeline dispatch.',
               [Path(__file__).resolve(), ROOT/'dsh/core/tools.py'])
