import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


class ControlledModel:
    def __init__(self):
        self.requests = []
        self.provider = 'mock'
        self.model = 'mock'

    async def chat_completion_stream(self, messages, tools=None, system=None):
        self.requests.append(dict(messages=copy.deepcopy(messages), tools=copy.deepcopy(tools), system=system))
        if len(self.requests) == 1:
            block = dict(type='tool-call', id='advance-call', name='advance', arguments='{}')
            yield dict(type='block-start', index=0, blockType='tool-call')
            yield dict(type='tool-call-delta', index=0, id='advance-call', name='advance', argumentsDelta='{}')
            yield dict(type='block-end', index=0, block=block)
            yield dict(type='finish', reason=dict(kind='tool-calls'))
        else:
            yield dict(type='block-start', index=0, blockType='text')
            yield dict(type='text-delta', index=0, text='finished')
            yield dict(type='block-end', index=0, block=dict(type='text', text='finished'))
            yield dict(type='finish', reason=dict(kind='stop'))


async def observe(action):
    from dsh.cordis.context import Context
    from dsh.core.agent_loop import AgentLoopPlugin
    from dsh.core.tools import ToolsPlugin
    from dsh.core.system_prompt import SystemPrompt

    ctx = Context()
    model = ControlledModel()
    ctx.set_service('llm', model)
    for plugin in (ToolsPlugin, SystemPrompt, AgentLoopPlugin):
        await ctx.plugin(plugin)
    current = '' if action == 'empty' else 'initial {{value}}'
    prompt = ctx.get('systemPrompt')
    prompt.variable('value', lambda *_: 'interpolated')
    prompt.context(dict(name='policy', order=10, text=lambda *_: current))

    async def advance(arguments, execution):
        nonlocal current
        current = 'changed {{value}}' if action == 'change' else '' if action == 'clear' else current
        return dict(changed=True)

    ctx.get('tools').register(dict(name='advance', description='Change dynamic context',
        parameters=dict(type='object', properties={}, additionalProperties=False), execute=advance,
        output=dict(schema=dict(type='object', properties=dict(changed=dict(type='boolean')),
            required=['changed'], additionalProperties=False), render=lambda *_: [dict(type='text', text='changed')])))
    parent = await ctx.get('agent_loop').create('parent')
    try:
        parent.agent.followup('advance context')
        await asyncio.wait_for(parent.agent.when_idle(), 10)
        snapshots = [copy.deepcopy(event['data']) for event in parent.agent.session.events
            if event['type'] == 'user/message'
            and event['data'].get('source', {}).get('plugin') == '@deepseek-ai/dsh-system-prompt']
        return dict(name=action, requests=model.requests, snapshots=snapshots)
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root, output = options.root.resolve(), options.output.resolve()
    if output.exists():
        raise ValueError('Fresh runtime context output required')
    sys.path.insert(0, str(root))
    observations = [await observe(action) for action in ('change', 'clear', 'same', 'empty')]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            relative = selected.relative_to(root).as_posix()
            modules[relative] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version,
            modules=modules, observations=observations), stream, ensure_ascii=True, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    asyncio.run(main())
