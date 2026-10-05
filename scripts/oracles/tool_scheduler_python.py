import argparse
import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--root', type=Path)
parser.add_argument('--output', type=Path, required=True)
options = parser.parse_args()
root = (options.root or Path(__file__).resolve().parents[2]).resolve()
sys.path.insert(0, str(root))

from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin, AgentLoopService
from dsh.core.session import SessionPlugin
from dsh.core.tools import ToolsPlugin
from dsh.settings.provider import SettingsProvider


class MemorySettings(SettingsProvider):
    def __init__(self, ctx=None, config=None):
        super().__init__(ctx)
        self.doc = {}

    def load(self):
        return copy.deepcopy(self.doc)

    async def _persist_section(self, namespace, section):
        self.doc[namespace] = copy.deepcopy(section)


class ToolModel:
    def __init__(self, count=12):
        self.requests = []
        self.count = count

    def chat_completion_stream(self, request=None, **arguments):
        self.requests.append(dict(request or {}, **arguments))
        if len(self.requests) == 1:
            for index in range(self.count):
                yield {'type': 'block-start', 'index': index, 'blockType': 'tool-call'}
                yield {'type': 'block-end', 'index': index, 'block': {
                    'type': 'tool-call', 'id': 'call-' + str(index), 'name': 'gated',
                    'arguments': json.dumps({'index': index}, separators=(',', ':'))}}
            yield {'type': 'finish', 'reason': {'kind': 'tool-calls'}}
        else:
            yield {'type': 'block-end', 'index': 0, 'block': {'type': 'text', 'text': 'done'}}
            yield {'type': 'finish', 'reason': {'kind': 'stop'}}


async def observe():
    rows = []
    for name, value in [('default', None), ('one', 1), ('whole-float', 2.0), ('zero', 0),
                        ('negative', -1), ('fraction', 1.5), ('boolean', True), ('text', '2'),
                        ('nan', float('nan')), ('infinite', float('inf'))]:
        ctx = Context()
        try:
            config = {} if value is None else {'maxParallelToolCalls': value}
            loop = AgentLoopService(ctx, config)
            rows.append(dict(name='cap-' + name, value=loop.config['maxParallelToolCalls']))
        except ValueError as error:
            rows.append(dict(name='cap-' + name, error=str(error)))
        finally:
            await ctx.fiber.dispose()
    for name, config, expected in [
        ('config-empty-session', {'agents': [{'id': 'main', 'sessionId': ''}]}, 'expected string length >= 1'),
        ('config-boolean-max-tokens', {'agents': [{'id': 'main', 'maxTokens': True}]}, 'expected number but got true'),
    ]:
        ctx = Context()
        published = []
        ctx.on('agent/created', lambda *arguments: published.append(True))
        await ctx.plugin(SessionPlugin)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(AgentPlugin)
        try:
            await ctx.plugin(AgentLoopPlugin, config)
            rows.append(dict(name=name, admitted=True, published=published))
        except Exception as error:
            rows.append(dict(name=name, error=getattr(error, 'name', type(error).__name__),
                             expected=expected in str(error), published=published))
        finally:
            await ctx.fiber.dispose()
    ctx = Context()
    try:
        settings_fiber = await ctx.plugin(MemorySettings)
        loop_fiber = await ctx.plugin(AgentLoopPlugin, {'agents': [], 'maxParallelToolCalls': 4})
        loop = ctx.get('agentLoop')
        settings = ctx.get('settings')
        descriptor = next(row for row in settings.describe() if row['ns'] == 'agent-loop')
        rows.append(dict(name='settings-entry', value=loop.config['maxParallelToolCalls'], keys=list(descriptor['value'])))
        await settings.update('agent-loop', {'maxParallelToolCalls': 1})
        rows.append(dict(name='settings-updated', value=loop.config['maxParallelToolCalls'], agents=loop.config['agents']))
        refused = False
        try:
            await settings.update('agent-loop', {'maxParallelToolCalls': 0})
        except (ValueError, TypeError):
            refused = True
        rows.append(dict(name='settings-refused', refused=refused, value=loop.config['maxParallelToolCalls']))
        await settings_fiber.dispose()
        rows.append(dict(name='settings-detached', value=loop.config['maxParallelToolCalls']))
        await ctx.plugin(MemorySettings)
        await ctx.get('settings').update('agent-loop', {'maxParallelToolCalls': 2})
        rows.append(dict(name='settings-replaced', value=loop.config['maxParallelToolCalls']))
        await loop_fiber.dispose()
        rows.append(dict(name='settings-unloaded', present=any(row['ns'] == 'agent-loop' for row in ctx.get('settings').describe())))
    finally:
        await ctx.fiber.dispose()
    ctx = Context()
    model = ToolModel(7)
    ctx.set_service('llm', model)
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(MemorySettings)
    await ctx.plugin(AgentLoopPlugin, {'agents': [], 'maxParallelToolCalls': 2})
    handle = await ctx.get('agents').create(session_id='group-snapshot')
    entered = [asyncio.Event() for index in range(7)]
    release = [asyncio.Event() for index in range(7)]
    active = [0, 0]
    peaks = [0, 0]
    started = []

    async def snapshot_body(arguments, execution):
        index = arguments['index']
        group = 0 if index < 3 else 1
        if index != 3:
            active[group] += 1
            peaks[group] = max(peaks[group], active[group])
        started.append(index)
        entered[index].set()
        try:
            if index != 3:
                await release[index].wait()
            if index == 0:
                await ctx.get('settings').update('agent-loop', {'maxParallelToolCalls': 1})
            return 'done-' + str(index)
        finally:
            if index != 3:
                active[group] -= 1

    ctx.get('tools').register({
        'name': 'gated', 'description': 'gated', 'parameters': {
            'type': 'object', 'properties': {'index': {'type': 'number'}}, 'required': ['index']},
        'isConcurrencySafe': lambda arguments, *remaining: arguments['index'] != 3,
        'execute': snapshot_body,
        'output': {'schema': {'type': 'string'}, 'render': lambda arguments, value: [{'type': 'text', 'text': value}]},
    })
    try:
        handle.agent.followup({'content': [{'type': 'text', 'text': 'go'}], 'source': {'kind': 'user'}})
        await asyncio.wait_for(entered[1].wait(), 3)
        initial = list(started)
        release[0].set()
        await asyncio.wait_for(entered[2].wait(), 3)
        continuation = list(started)
        release[1].set()
        release[2].set()
        for index in range(4, 7):
            await asyncio.wait_for(entered[index].wait(), 3)
            release[index].set()
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        rows.append(dict(name='model-group-snapshot', initial=initial, continuation=continuation,
                         peaks=peaks, started=started, cap=ctx.get('agentLoop').config['maxParallelToolCalls'],
                         requests=len(model.requests), results=[event['data']['message']['source']['callId']
                         for event in handle.agent.session.events if event['type'] == 'tool/result']))
    finally:
        for gate in release:
            gate.set()
        await handle.dispose()
        await ctx.fiber.dispose()
    for cap in [1, 2, 10]:
        ctx = Context()
        model = ToolModel()
        ctx.set_service('llm', model)
        await ctx.plugin(SessionPlugin)
        await ctx.plugin(ToolsPlugin)
        await ctx.plugin(AgentPlugin)
        await ctx.plugin(AgentLoopPlugin, {'agents': [], 'maxParallelToolCalls': cap})
        handle = await ctx.get('agents').create(session_id='pool-' + str(cap), agent_options={'provider': 'mock', 'model': 'mock'})
        entered, release = asyncio.Event(), asyncio.Event()
        active, peak = 0, 0
        started = []

        async def body(arguments, execution):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            started.append(arguments['index'])
            if len(started) == cap:
                entered.set()
            try:
                await release.wait()
                return 'done-' + str(arguments['index'])
            finally:
                active -= 1

        ctx.get('tools').register({
            'name': 'gated', 'description': 'gated', 'parameters': {
                'type': 'object', 'properties': {'index': {'type': 'number'}}, 'required': ['index']},
            'isConcurrencySafe': lambda *arguments: True, 'execute': body,
            'output': {'schema': {'type': 'string'}, 'render': lambda arguments, value: [{'type': 'text', 'text': value}]},
        })
        try:
            handle.agent.followup({'content': [{'type': 'text', 'text': 'go'}], 'source': {'kind': 'user'}})
            await asyncio.wait_for(entered.wait(), 3)
            release.set()
            await asyncio.wait_for(handle.agent.when_idle(), 3)
            rows.append(dict(name='model-pool-' + str(cap), peak=peak, started=started,
                requests=len([event for event in handle.agent.session.events if event['type'] == 'assistant/message']),
                results=[dict(callId=event['data']['message']['source']['callId'], isError=event['data']['message']['content'][0]['isError'])
                         for event in handle.agent.session.events if event['type'] == 'tool/result']))
        finally:
            release.set()
            await handle.dispose()
            await ctx.fiber.dispose()
    return rows


if __name__ == '__main__':
    rows = asyncio.run(observe())
    modules = {}
    for name, module in sorted(sys.modules.items()):
        if not name.startswith('dsh') or not getattr(module, '__file__', None):
            continue
        path = Path(module.__file__).resolve()
        relative = path.relative_to(root).as_posix()
        if not relative.startswith('dsh/') or path.suffix != '.py':
            raise ValueError('runtime module escaped selected root')
        modules[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    options.output.write_text(json.dumps(dict(root=str(root), python=sys.version.split()[0], modules=modules,
                                              rows=rows), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
