import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
ROOT = options.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.core.tool_calls import execute_tool_calls
from dsh.llm.error import HarnessError
from dsh.llm.llm_service import LlmRuntime


WORK = Path(__file__).resolve().parent


async def main():
    rows = []
    cases = json.loads((WORK / 'tool-durable-cases.json').read_text(encoding='utf-8'))
    for spec in cases:
        ctx = Context()
        handle = None
        try:
            for plugin in (LlmRuntime, SessionPlugin, SystemPrompt, ToolsPlugin, AgentPlugin):
                await ctx.plugin(plugin)
            await ctx.plugin(AgentLoopPlugin, dict(agents=[], maxParallelToolCalls=1))
            handle = await ctx.get('agents').create(session_id='durable-' + spec['name'])
            agent = handle.agent
            signal = asyncio.Event()
            calls, public_results = [], []

            def render(arguments, value):
                return [dict(type='text', text=value)]

            async def execute(arguments, execution):
                calls.append(arguments['identity'])
                if spec.get('abort') == 'body':
                    signal.set()
                if spec.get('throw') == 'plain':
                    raise RuntimeError('plain failure')
                if spec.get('throw') == 'typed':
                    raise HarnessError('typed failure', 'CONTROLLED_TYPED')
                return 'body value'

            def observed(execution, result):
                value = dict(content=result.content, isError=result.is_error)
                if not result.is_error:
                    value['value'] = result.value
                if result.error is not None:
                    value['error'] = result.error
                if getattr(result, '_meta_present', result.meta is not None):
                    value['meta'] = result.meta
                if result.additional_contexts:
                    value['additionalContexts'] = result.additional_contexts
                if result.concludes_turn:
                    value['concludesTurn'] = True
                public_results.append(copy.deepcopy(value))

            output = dict(schema=dict(type='string'), render=render)
            if 'meta' in spec:
                output['presentationMeta'] = lambda arguments, value: spec['meta']
            ctx.get('tools').register(dict(name='probe', description='Controlled complete durable result.',
                parameters=dict(type='object', properties=dict(identity=dict(type='string')),
                    required=['identity'], additionalProperties=False), isConcurrencySafe=lambda arguments: False,
                output=output, execute=execute))
            ctx.on('tools/result', observed)
            if spec.get('abort') == 'before':
                signal.set()
            outcome = await execute_tool_calls(agent.ctx, agent, 1, 1,
                [dict(type='tool-call', id=identity, name='probe',
                      arguments=json.dumps(dict(identity=identity), separators=(',', ':')))
                 for identity in ('c1', 'c2', 'c3')], signal, max_parallel=1)
            rows.append(dict(name=spec['name'], calls=calls, outcome=outcome, publicResults=public_results,
                events=copy.deepcopy([event for event in agent.session.events if event['type'] in ('tool/call', 'tool/result')])))
        finally:
            if handle is not None:
                await handle.dispose()
            await ctx.fiber.dispose()
    return rows


with patch('time.time', lambda: 1791331200):
    rows = asyncio.run(main())
imports = {}
for name, module in sorted(sys.modules.items()):
    filename = getattr(module, '__file__', None)
    if filename and (name == 'dsh' or name.startswith('dsh.')):
        selected = Path(filename).resolve()
        imports[selected.relative_to(ROOT).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
report = dict(root=str(ROOT), python=sys.version, executable=sys.executable, imports=imports, rows=rows,
    fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
with options.output.open('x', encoding='utf-8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
