import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace


parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
arguments = parser.parse_args()
selected_root = arguments.root.resolve()
work = Path(os.environ['DSH_FS_FIXTURE_WORK'])
sys.path.insert(0, str(selected_root))
from dsh.cordis.context import Context
from dsh.core.abort import AbortController
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin, ToolExecutionInput
from dsh.fs.fs_local import FsLocalPlugin
from dsh.fs.fs_observation_policy import FsObservationPolicyPlugin
from dsh.fs.tool_fs import ToolFsPlugin


class Owner:
    def __init__(self, destination):
        self.header = dict(cwd=str(destination))


async def observe(fixture):
    destination = work / 'fs-real-tool-shared-v1' / fixture['name']
    assert destination.is_dir()
    target = destination / 'target.txt'
    if target.exists():
        target.unlink()
    if fixture['initial'] is not None:
        target.write_bytes(fixture['initial'].encode('utf-8'))
    ctx, signal, steps = Context(), AbortController().signal, []
    agent = None if fixture.get('noAgent') else SimpleNamespace(session=Owner(destination))
    try:
        await ctx.plugin(SystemPrompt)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(FsLocalPlugin, dict(cwd=str(destination)))
        policy = await ctx.plugin(FsObservationPolicyPlugin)
        mounted = await ctx.plugin(ToolFsPlugin, dict(readLimit=10, readStreamMinSize=1, **fixture.get('caps', {})))
        tools = ctx.get('tools')
        for step in fixture['steps']:
            if 'external' in step:
                target.write_bytes(step['external'].encode('utf-8'))
                steps.append(dict(external=step['external']))
                continue
            if 'policy' in step:
                if step['policy'] == 'unload':
                    await policy.dispose()
                else:
                    policy = await ctx.plugin(FsObservationPolicyPlugin)
                steps.append(dict(policy=step['policy']))
                continue
            result = await tools.execute(ToolExecutionInput(name=step['tool'], arguments=step['args'], call_id='real-fixture', signal=signal, agent=agent))
            value = dict(isError=result.isError, content=copy.deepcopy(result.content))
            for name in ('value', 'error', 'meta'):
                item = getattr(result, name)
                if item is not None:
                    value[name] = copy.deepcopy(item)
            if result.additional_contexts:
                value['additionalContexts'] = copy.deepcopy(result.additional_contexts)
            tool = tools.get(step['tool'])
            steps.append(dict(tool=step['tool'], result=value, call=tool.present_call(step['args']), replay=tool.present_result(step['args'], value)))
        await mounted.dispose()
        return dict(name=fixture['name'], steps=steps, afterHex=target.read_bytes().hex() if target.exists() else None,
            afterUnload=[tools.get(name) is not None for name in ('read', 'write', 'edit')])
    finally:
        await ctx.fiber.dispose()


async def main():
    fixture_path = Path(__file__).resolve().parent / 'fs-real-tool-fixtures-v1.json'
    rows = [await observe(fixture) for fixture in json.loads(fixture_path.read_text(encoding='utf-8'))['cases']]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        filename = getattr(module, '__file__', None)
        if filename and (name == 'dsh' or name.startswith('dsh.')):
            path = Path(filename).resolve()
            modules[path.relative_to(selected_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    with arguments.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(selected_root), executable=sys.executable, python=sys.version, modules=modules,
            fixtureSha256=hashlib.sha256(fixture_path.read_bytes()).hexdigest(), rows=rows), stream, indent=2, ensure_ascii=True)
        stream.write('\n')


asyncio.run(main())
