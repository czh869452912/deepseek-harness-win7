"""Observe real Python AgentLoop calls, reminders and next model requests."""
import asyncio
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.cordis.context import Context
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin
from dsh.guard.repeat_tool_reminder import RepeatToolReminderPlugin


class Model:
    provider, model = 'fixture', 'fixture'

    def __init__(self, turns):
        self.calls = [call for turn in turns for call in list(turn) + [None]]
        self.requests = []

    async def chat_completion_stream(self, messages, tools=None, **_kwargs):
        self.requests.append(copy.deepcopy(messages))
        if not self.calls:
            raise RuntimeError('fixture response budget exhausted')
        call = self.calls.pop(0)
        if call is None:
            yield dict(choices=[dict(delta=dict(role='assistant', content='done'), finish_reason='stop')])
        else:
            name, args = call
            yield dict(choices=[dict(delta=dict(role='assistant', tool_calls=[dict(index=0,
                id='call-{}'.format(len(self.requests)), type='function', function=dict(name=name, arguments=args))]),
                finish_reason='tool_calls')])


def notice_texts(messages):
    texts = []
    for message in messages:
        content = message.get('content', [])
        for text in ([content] if isinstance(content, str) else [block['text'] for block in content if block.get('type') == 'text']):
            if text.startswith(('You are repeating the exact same tool call', 'Repeated tool call detected:')):
                texts.append(text)
    return texts


async def run():
    cases = json.loads((ROOT / 'scripts/oracles/repeat-tool-cases.json').read_text(encoding='utf-8'))
    rows = []
    for spec in cases:
        ctx, model = Context(), Model(spec['turns'])
        ctx.set_service('llm', model)
        handle = None
        try:
            await ctx.plugin(SessionPlugin)
            await ctx.plugin(ToolsPlugin)
            await ctx.plugin(SystemPrompt)
            await ctx.plugin(AgentLoopPlugin)
            await ctx.plugin(RepeatToolReminderPlugin, spec['config'])
            received = []
            def tool(args, _exec):
                received.append(json.dumps(args, ensure_ascii=True, separators=(',', ':')))
                return [dict(type='text', text='ok')]
            for name in ('probe', 'other'):
                ctx.get('tools').register(dict(name=name, description='fixture', parameters={},
                    execute=tool,
                    output=dict(schema={}, render=lambda _args, value: value)))
            policy = spec.get('policy')
            if policy == 'deny':
                ctx.on('tools/pre-execute', lambda *_: dict(kind='deny', reason='sealed'))
            if policy == 'block':
                ctx.on('tools/post-execute', lambda *_: dict(kind='block', feedback=[dict(type='text', text='blocked')]))
            if policy == 'replace':
                ctx.on('tools/post-execute', lambda *_: dict(kind='accept', value=[dict(type='text', text='replaced')]))
            handle = await ctx.get('agent_loop').create(spec['mode'])
            for _turn in spec['turns']:
                handle.agent.followup('go')
                await asyncio.wait_for(handle.agent.when_idle(), 3)
            events = handle.agent.session.events
            if spec['mode'] == 'proto-key-loss':
                assert received == [call[1] for call in spec['turns'][0]], 'the tool must receive both distinct proto values'
            rows.append(dict(mode=spec['mode'],
                notices=[dict(content=e['data']['content'], source=e['data']['source']) for e in events
                         if e['type'] == 'user/message' and e['data'].get('source', {}).get('plugin') == 'repeat-tool-reminder'],
                requests=[notice_texts(request) for request in model.requests],
                results=[dict(isError=e['data']['message']['content'][0].get('isError', False),
                              content=e['data']['message']['content'][0]['content'])
                         for e in events if e['type'] == 'tool/result']))
        finally:
            if handle is not None:
                await handle.dispose()
            await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(run()), indent=2, ensure_ascii=True) + '\n', encoding='utf-8')
