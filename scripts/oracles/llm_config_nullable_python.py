import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
root = arguments.root.resolve()
sys.path.insert(0, str(root))
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.llm.llm_service import LlmRuntime


async def observe(method, name):
    ctx = Context()
    await ctx.plugin(LlmRuntime)
    trace = []
    signal = AbortController().signal
    class Adapter:
        async def resolve_model(self, provider, model, selected_signal=None):
            trace.append(dict(kind='resolve', provider=provider, id=model, signalSame=selected_signal is signal))
            info = dict(provider=provider, id=model, name=model, defaultMaxTokens=4096)
            if name != 'null-no-reasoning':
                info['reasoning'] = dict(efforts=[dict(id='low', name='Low')])
                if name != 'null-no-default':
                    info['reasoning']['defaultEffort'] = 'low'
            return info
        async def stream(self, options):
            yield dict(type='finish', reason=dict(kind='stop'))
    ctx.get('llm').register_adapter(['fixture'], Adapter())
    config = dict(provider='fixture', model='model', stop=['done'])
    if name.startswith('null-') and name != 'null-max':
        config['reasoningEffort'] = None
    if name == 'bool-default':
        config['reasoningEffort'] = True
    if name == 'number-default':
        config['reasoningEffort'] = 1
    if name == 'null-max':
        config['maxTokens'] = None
    if name == 'explicit-zero':
        config['maxTokens'] = 0
    try:
        result = await getattr(ctx.get('llm'), method)(config, signal)
        if method == 'prepareCall':
            state = {key: value for key, value in result.items() if key != 'stream' and value is not None}
            observed = dict(result=state, input=copy.deepcopy(config), sameConfig=state['config'] is config, sameStop=state['config']['stop'] is config['stop'])
        else:
            observed = dict(result=result, input=copy.deepcopy(config), sameConfig=result is config, sameStop=result['stop'] is config['stop'])
    except Exception as error:
        observed = dict(error=dict(name=getattr(error, 'name', type(error).__name__), message=getattr(error, 'message', str(error)), **(dict(code=error.code) if hasattr(error, 'code') else {})), input=copy.deepcopy(config))
    finally:
        await ctx.fiber.dispose()
    return dict(name=method+'/'+name, trace=trace, observed=observed)


names = ('absent-default', 'null-default', 'null-no-default', 'null-no-reasoning', 'bool-default', 'number-default', 'null-max', 'explicit-zero')
rows = [asyncio.run(observe(method, name)) for method in ('resolveCallConfig', 'prepareCall') for name in names]
modules = {}
for name, module in sorted(sys.modules.items()):
    source = getattr(module, '__file__', None)
    if source and (name == 'dsh' or name.startswith('dsh.')):
        path = Path(source).resolve()
        modules[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
with arguments.output.open('x', encoding='utf-8') as stream:
    json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules, rows=rows), stream, indent=2)
    stream.write('\n')
