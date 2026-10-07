"""Run the same tool consumer inputs through the actual native registrations."""
import asyncio
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.tools import Tool
from dsh.extensions.cordis_manager import CordisManagerPlugin
from dsh.extensions.cordis_prompt import native_contracts
from dsh.extensions.host_runner import DynamicCordisRunner


def environment(spec):
    fixture = copy.deepcopy(spec.get('fixture', {}))
    tools, hooks, sections, calls = [], {}, [], []
    fiber = NS(inject=dict(present={}, missing={}))
    fiber.parent = NS(fiber=fiber)
    child = NS(parent=NS(fiber=fiber), inject={})
    foreign = NS(inject={})
    foreign.parent = NS(fiber=foreign)
    if spec.get('live'):
        for row in fixture.get('snapshot', []):
            if 'activeRun' in row:
                row['activeRun']['fiber'] = fiber
    async def receipt(*args, **kwargs):
        return fixture['receipt']
    def reference(agent, pid):
        calls.append(pid)
        return fixture.get('references', {}).get(pid)
    runner = NS(listPlugins=lambda *_: fixture.get('plugins', []), inspectPlugin=lambda *_: fixture.get('plugin'),
        inspectPackage=lambda *_: fixture.get('inspected'), snapshot=lambda *_: fixture.get('snapshot', []),
        reference=reference, define=lambda *_: fixture['receipt'], run=receipt, stop=receipt, undefine=receipt)
    def register(definition):
        tool = Tool(definition['name'], definition['description'], definition['parameters'], definition['execute'],
            output=definition['output'], present_call=definition['presentCall'], canonical=True)
        tools.append(tool)
    async def query(*_):
        return fixture.get('data')
    services = dict(tools=NS(register=register), dynamicCordisRunner=runner, systemPrompt=NS(section=sections.append),
        cordisInspect=NS(register=lambda *_: lambda: None, list=lambda: [], query=query), present=0)
    ctx = NS(reflect=NS(store={1: NS(name='zeta', fiber=fiber), 2: NS(name='alpha', fiber=child), 3: NS(name='foreign', fiber=foreign)}),
        get=services.get, effect=lambda fn, label='': fn(), on=lambda name, fn: hooks.update({name: fn}))
    CordisManagerPlugin().apply(ctx)
    return tools, hooks, sections, calls


async def observe(spec):
    tools, hooks, sections, calls = environment(spec)
    kind = spec['kind']
    if kind in ('presentation', 'execute', 'render-error'):
        tool = next(tool for tool in tools if tool.name == spec.get('tool', 'cordis_run'))
        if kind == 'presentation':
            return tool.present_call(spec['args'])
        if kind == 'render-error':
            return tool.output['presentationMeta']({}, spec['value'])
        value = await tool.execute(spec['args'], NS(signal=NEVER_ABORTED, **({} if spec.get('noAgent') else dict(agent=NS(id='owner')))))
        return dict(value=value, render=tool.output['render'](spec['args'], value),
                    meta=tool.output['presentationMeta'](spec['args'], value) if 'presentationMeta' in tool.output else None)
    if kind == 'pre-step':
        controller = AbortController()
        async def next_fn():
            if spec.get('abort'):
                controller.abort(ValueError('stop reference'))
            return copy.deepcopy(spec['decision'])
        decision = await hooks['agent/pre-step'](dict(agent=NS(id='owner'), messages=spec['messages'], signal=controller.signal), next_fn)
        result = {key: value for key, value in decision.items() if key != 'messages'}
        if 'messages' in decision:
            result['messages'] = []
            for message in decision['messages']:
                if message.get('source', {}).get('plugin') == 'tool-cordis':
                    if not isinstance(message.get('id'), str):
                        raise ValueError('injected message has no identity')
                    message = {key: value for key, value in message.items() if key != 'id'}
                result['messages'].append(message)
        result['lookups'] = calls
        return result
    if kind in ('mints', 'runner-views', 'plan'):
        runner = object.__new__(DynamicCordisRunner)
        runner.plugins, runner._next_ids = {}, dict(plugin=1, package=1, run=1, approval=1)
        runner._closed, runner._ending = False, {}
        if kind == 'mints':
            return [runner.mint_id('plugin', 'theme'), runner.mint_id('plugin', 'panel'), runner.mint_id('package', 'pkg'),
                runner.mint_id('package', 'pkg'), runner.mint_id('run', 'run'), runner.mint_id('run', 'run'),
                runner.mint_id('approval', 'approval'), runner.mint_id('plugin', 'theme')]
        for row in copy.deepcopy(spec['plugins']):
            row['packages'] = {package['packageId']: package for package in row['packages']}
            runner.plugins[row['pluginId']] = row
        if kind == 'plan':
            runner.starting = {}
            if spec.get('starting'):
                runner.starting['theme-1'] = object()
            plugin, error = runner.plan(NS(id=spec.get('agentId', 'owner')), spec.get('pluginId', 'theme-1'),
                spec.get('packageId', 'pkg-2'), spec['activationMode'], spec.get('attach', False))
            return dict(ok=True) if error is None else dict(ok=False, response=error)
        return getattr(runner, spec['method'])(NS(id=spec.get('agentId', 'owner')), *spec.get('ids', []))
    raise ValueError('unknown observation ' + kind)


async def observations():
    cases = []
    for spec in json.loads((ROOT / 'scripts/oracles/cordis-tools-cases.json').read_text(encoding='utf-8')):
        try:
            cases.append(dict(mode=spec['mode'], value=await observe(spec)))
        except Exception as error:
            cases.append(dict(mode=spec['mode'], error=dict(message=getattr(error, 'message', str(error)))))
    contracts = native_contracts()
    tools, _, _, _ = environment({})
    definitions = [dict(name=tool.name, description=tool.description, parameters=tool.parameters,
        outputSchema=tool.output['schema']) for tool in tools]
    return dict(cases=cases, definitions=definitions, prompt=contracts['prompt'], order=contracts['order'])


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observations()), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
