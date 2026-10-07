import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys


ACTIONS = ('change', 'clear', 'same', 'empty')
CONFIGURATIONS = ('base', 'max-tokens', 'reasoning', 'both')
NAMES = tuple(action + '/' + configuration for action in ACTIONS for configuration in CONFIGURATIONS)


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


async def observe(name):
    if name not in NAMES:
        raise ValueError('Unknown runtime full request observation')
    action, configuration = name.split('/')
    from dsh.cordis.context import Context
    from dsh.core.agent_loop import AgentLoopPlugin
    from dsh.core.agent import AgentPlugin
    from dsh.core.session import SessionPlugin
    from dsh.core.agent import AgentOptions
    from dsh.core.abort import AbortSignal
    from dsh.core.tools import ToolsPlugin
    from dsh.core.system_prompt import SystemPrompt
    from dsh.llm.llm_service import LlmRuntime

    class Adapter:
        def __init__(self):
            self.script = ControlledModel()
            self.requests = []
            self.signals = []

        async def prepare_call(self, provider, model, signal=None):
            info = dict(provider=provider, id=model, name=model)
            if configuration in ('reasoning', 'both'):
                info['reasoning'] = dict(efforts=[dict(id='high', name='High')], defaultEffort='high')
            return dict(model=info, stream=self.stream)

        async def stream(self, request):
            signal = request['signal']
            self.signals.append(signal)
            serialized = {key: dict(present=isinstance(signal, AbortSignal), aborted=signal.aborted, sameAsFirst=signal is self.signals[0]) if key == 'signal' else copy.deepcopy(value) for key, value in request.items()}
            self.requests.append(serialized)
            async for chunk in self.script.chat_completion_stream(request['messages'], request.get('tools'), request.get('system')):
                yield chunk

    ctx = Context()
    await ctx.plugin(LlmRuntime)
    model = ctx.get('llm')
    adapter = Adapter()
    model.register_adapter(['mock'], adapter)
    for plugin in (ToolsPlugin, SystemPrompt, SessionPlugin, AgentPlugin, AgentLoopPlugin):
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
    options = dict(provider='mock', model='mock')
    if configuration in ('max-tokens', 'both'):
        options['maxTokens'] = 17
    if configuration in ('reasoning', 'both'):
        options['reasoningEffort'] = 'high'
    parent = await ctx.get('agent_loop').create('parent', options=AgentOptions(provider=options['provider'],
        model=options['model'], max_tokens=options.get('maxTokens'), reasoning_effort=options.get('reasoningEffort')))
    try:
        parent.agent.followup('advance context')
        await asyncio.wait_for(parent.agent.when_idle(), 10)
        snapshots = [copy.deepcopy(event['data']) for event in parent.agent.session.events
            if event['type'] == 'user/message'
            and event['data'].get('source', {}).get('plugin') == '@deepseek-ai/dsh-system-prompt']
        assert len(adapter.requests) == 2 and len(adapter.signals) == 2, (name, adapter.requests, parent.agent.session.events)
        assert adapter.signals[0] is adapter.signals[1]
        assert not adapter.signals[0].is_set()
        return dict(name=name, requests=adapter.requests, snapshots=snapshots)
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    root = options.root.resolve()
    sys.path.insert(0, str(root))
    rows = [asyncio.run(observe(name)) for name in NAMES]
    modules = {}
    for name, module in sorted(sys.modules.items()):
        path = getattr(module, '__file__', None)
        if path and (name == 'dsh' or name.startswith('dsh.')):
            selected = Path(path).resolve()
            modules[selected.relative_to(root).as_posix()] = hashlib.sha256(selected.read_bytes()).hexdigest()
    with options.output.open('x', encoding='utf-8') as stream:
        json.dump(dict(root=str(root), executable=sys.executable, python=sys.version, modules=modules,
            observations=rows, scope='Actual canonical LlmRuntime/LLMService/prepared adapter captures complete serialized GenerateOptions for16 context/configuration combinations. Signal facade records actual presence/type, aborted state and same-as-first ownership; native presence, shared identity and nonaborted state are independently asserted. Not full signal ABI or acceptance. No product mutation.'), stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    main()
