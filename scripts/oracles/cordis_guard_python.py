"""Observe the real native Guard with the shared source-boundary inputs."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.core.session.json import UNDEFINED
from dsh.extensions.cordis_guard import sandbox_define_tool, sandbox_register_tool, guarded_plugin, normalize_handler


def value(spec):
    recipe = spec.get('recipe')
    if recipe == 'undefined':
        return UNDEFINED
    if recipe == 'nan':
        return float('nan')
    if recipe == 'negative-zero':
        return -0.0
    if recipe == 'function':
        return lambda: None
    if recipe == 'cycle':
        result = {}
        result['again'] = result
        return result
    if recipe == 'decorated':
        class Decorated(list):
            pass
        result = Decorated([1])
        result.hidden = True
        return result
    if recipe == 'nested-undefined':
        return dict(nested=[1, dict(invalid=UNDEFINED)])
    if recipe == 'preview':
        return ['x' * 200]
    if recipe == 'unicode-preview':
        return ['😀' * 100]
    return spec.get('value')


def definition(parameters=None, schema=None):
    return dict(name='guard_probe', description='Actual guard', parameters={} if parameters is None else parameters,
        output=dict(schema=dict(type='json') if schema is None else schema, render=lambda *_: [], presentationMeta=lambda args, v: v),
        execute=lambda *_: None)


def project(tool):
    return dict(name=tool['name'], description=tool['description'], parameters=tool['parameters'], outputSchema=tool['output']['schema'])


def observed(value):
    return dict(undefined=True) if value is UNDEFINED else value


async def observe(spec):
    options, kind = definition(), spec['kind']
    if kind == 'parameters':
        options['parameters'] = spec['value']
        return project(sandbox_define_tool(options))
    if kind == 'schema':
        options['output']['schema'] = spec['value']
        return project(sandbox_define_tool(options))
    if kind == 'invalid-option':
        flag = spec['value']
        if flag == 'options':
            options = 42
        elif flag == 'output':
            options['output'] = None
        elif flag == 'timeout':
            options['timeoutMs'] = False
        elif flag == 'execute':
            options['execute'] = True
        else:
            options['output'][flag] = True
        return project(sandbox_define_tool(options))
    if kind == 'execute':
        options['execute'] = lambda *_: value(spec)
        return observed(await sandbox_define_tool(options)['execute']({}, {}))
    if kind in ('render', 'meta'):
        key = 'render' if kind == 'render' else 'presentationMeta'
        options['output'][key] = lambda *_: value(spec)
        return observed(sandbox_define_tool(options)['output'][key]({}, None))
    if kind == 'handler':
        return observed(await normalize_handler(spec.get('method', 'read'), False if spec.get('invalidCallback') else lambda _: value(spec))[1]({}))
    if kind == 'soft':
        options = definition(dict(x=dict(type='string', required=True)))
        options.update(presentCall=lambda *_: dict(title='call'), presentResult=lambda *_: dict(title='result'), isConcurrencySafe=lambda *_: True)
        tool, args = sandbox_define_tool(options), dict(x='ok') if spec['valid'] else {}
        return dict(call=observed(tool['presentCall'](args)), result=observed(tool['presentResult'](args, {})), concurrency=tool['isConcurrencySafe'](args))
    if kind == 'depth':
        schema = dict(type='string')
        for _ in range(spec['value']):
            schema = dict(type='array', items=schema)
        node = sandbox_define_tool(definition(dict(x=schema), schema))['output']['schema']
        depth = 0
        while node.get('type') == 'array':
            depth += 1
            node = node['items']
        return dict(depth=depth, leaf=node)
    ctx = Context()
    await ctx.plugin(ToolsPlugin())
    try:
        if kind == 'marker':
            tool = sandbox_define_tool(options)
            sandbox_register_tool(ctx, tool if spec['variant'] == 'real' else dict(tool) if spec['variant'] == 'spread' else options)
            return dict(schemas=ctx.get('tools').schemas())
        if kind == 'facade':
            captured, reports = [], []
            async def async_context():
                return ctx
            ctx.provide('demo', NS(value='ready', sync=lambda: ctx, context=ctx, **{'async': async_context}))
            ctx.provide('directContext', ctx)
            ctx.provide('callable', async_context if spec['operation'] == 'callable-async-context' else (lambda: 'ready') if spec['operation'] == 'callable-data' else (lambda: ctx))
            await ctx.plugin(guarded_plugin(dict(inject=['demo', 'tools'] if spec['operation'] == 'tools-declared' else ['demo'], apply=captured.append), lambda error: reports.append(str(error))))
            facade, operation = captured[0], spec['operation']
            try:
                if operation == 'write':
                    facade.stash = 1
                    result = None
                elif operation == 'undeclared':
                    result = facade.directContext
                elif operation == 'optional':
                    result = facade.get('absent')
                elif operation == 'declared':
                    result = facade.demo.value
                elif operation == 'service-write':
                    facade.demo.value = 'changed'
                    result = facade.demo.value
                elif operation in ('tools-view', 'tools-declared'):
                    sandbox_register_tool(ctx, sandbox_define_tool(options))
                    result = dict(get=facade.tools.get('guard_probe'), schemas=facade.get('tools').schemas(), execute='execute' in facade.tools.get('guard_probe'))
                elif operation == 'has':
                    result = [key in facade for key in ('tools','get','on','timer','timeout','demo','root','fiber','missing')]
                elif operation == 'sync-context':
                    result = facade.demo.sync()
                elif operation == 'index-context':
                    result = facade.demo['sync']()
                elif operation == 'async-context':
                    result = await getattr(facade.demo, 'async')()
                elif operation == 'property-context':
                    result = facade.demo.context
                elif operation == 'direct-context':
                    result = facade.get('directContext')
                elif operation == 'callable-data':
                    result = facade.get('callable')()
                elif operation == 'callable-context':
                    result = dict(escaped=facade.get('callable')() is ctx)
                elif operation == 'callable-async-context':
                    result = dict(escaped=(await facade.get('callable')()) is ctx)
                else:
                    result = getattr(facade, operation)
                return dict(value=observed(result), reports=reports)
            except Exception as error:
                return dict(error=dict(message=str(error)), reports=reports)
        raise ValueError('unknown kind')
    finally:
        await ctx.fiber.dispose()


async def observations():
    result = []
    for spec in json.loads((ROOT / 'scripts/oracles/cordis-guard-cases.json').read_text(encoding='utf-8')):
        try:
            result.append(dict(mode=spec['mode'], value=await observe(spec)))
        except Exception as error:
            details = dict(message=getattr(error, 'message', str(error)))
            if getattr(error, 'code', None):
                details.update(code=error.code, name=error.name, violations=error.violations)
            result.append(dict(mode=spec['mode'], error=details))
    return result


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observations()), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
