import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
ROOT = options.root.resolve()
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.llm.error import HarnessError


async def main():
    rows = []
    ctx = Context()
    try:
        await ctx.plugin(ToolsPlugin)
        rows.append(dict(name='before-prompt', present=ctx.get('tools') is not None))
        prompt = await ctx.plugin(SystemPrompt)
        rows.append(dict(name='after-prompt', present=ctx.get('tools') is not None))
        await prompt.dispose()
        await asyncio.sleep(0)
        rows.append(dict(name='after-prompt-dispose', present=ctx.get('tools') is not None))
        await ctx.plugin(SystemPrompt)
        rows.append(dict(name='after-prompt-restore', present=ctx.get('tools') is not None))
    finally:
        await ctx.fiber.dispose()
    for name in ('plain', 'typed', 'unknown', 'pre-aborted', 'body-aborted'):
        ctx = Context()
        calls = []
        controller = AbortController()
        try:
            await ctx.plugin(SystemPrompt)
            await ctx.plugin(ToolsPlugin)

            async def execute(arguments, execution):
                calls.append(True)
                if name == 'plain':
                    raise RuntimeError('plain failure')
                if name == 'typed':
                    raise HarnessError('typed failure', 'CONTROLLED_TYPED')
                if name == 'body-aborted':
                    controller.abort(RuntimeError('body cancelled'))
                return 'body value'

            ctx.get('tools').register(dict(name='sample', description='Controlled error result.', parameters={},
                output=dict(schema=dict(type='string'), render=lambda arguments, value: [dict(type='text', text=value)]),
                execute=execute))
            if name == 'pre-aborted':
                controller.abort(RuntimeError('pre cancelled'))
            result = await ctx.get('tools').execute(ToolExecutionInput('controlled-call',
                'missing' if name == 'unknown' else 'sample', {}, signal=controller.signal))
            public = dict(content=result.content, isError=result.is_error)
            if result.error is not None:
                public['error'] = result.error
            if result.meta is not None:
                public['meta'] = result.meta
            if result.additional_contexts:
                public['additionalContexts'] = result.additional_contexts
            if result.concludes_turn:
                public['concludesTurn'] = True
            rows.append(dict(name=name, calls=len(calls), result=public))
        finally:
            await ctx.fiber.dispose()
    imports = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            imports[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(root=str(ROOT), python=sys.version, executable=sys.executable, imports=imports, rows=rows,
        fixtureSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')


asyncio.run(main())
