import asyncio
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from dsh.cordis import Context
from dsh.core.abort import AbortSignal
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.system_prompt import SystemPrompt
from dsh.core.tools import ToolsPlugin


class Model:
    provider, model = 'fixture', 'fixture'

    def __init__(self, tools=False, queued=False):
        self.requests, self.tools, self.queued = [], tools, queued

    async def chat_completion_stream(self, messages, tools=None, **kwargs):
        self.requests.append(messages)
        if self.queued and len(self.requests) in (1, 3):
            delta = {'tool_calls': [{'index': 0, 'id': 'queued-' + str(len(self.requests)), 'type': 'function',
                'function': {'name': 'queued_probe', 'arguments': '{}'}}]}
        elif self.tools and len(self.requests) <= 2:
            delta = {'tool_calls': [{'index': 0, 'id': 'signal-' + str(len(self.requests)), 'type': 'function',
                'function': {'name': 'signal_probe', 'arguments': '{}'}}]}
        else:
            delta = {'content': 'next turn completed' if self.tools else 'recovered after cancellation'}
        yield {'choices': [{'delta': delta, 'finish_reason': 'tool_calls' if 'tool_calls' in delta else 'stop'}]}


async def harness(tools=False, queued=False):
    ctx, model = Context(), Model(tools, queued)
    ctx.set_service('llm', model)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(SystemPrompt)
    await ctx.plugin(AgentLoopPlugin)
    handle = await ctx.get('agents').create({'sessionId': 'signal-owner'})
    return ctx, model, handle


def turn_reasons(agent):
    return [event['data']['reason'] for event in agent.session.events if event['type'] == 'turn/end']


async def observations():
    output = {}
    cause = {'kind': 'user', 'detail': 'actual cancellation reason'}
    ctx, model, handle = await harness(True)
    signals, notifications, ready = [], [], asyncio.Event()
    async def execute(args, execution):
        signal = execution.signal
        if not isinstance(signal, AbortSignal):
            raise TypeError('actual tool signal is not an AbortSignal')
        signals.append(signal)
        def cancelled(event):
            notifications.append(event.target.reason)
        signal.addEventListener('abort', cancelled, {'once': True})
        try:
            if len(signals) == 1:
                ready.set()
                await signal.wait_aborted()
            return 'signal generation consumed'
        finally:
            signal.removeEventListener('abort', cancelled)
    ctx.get('tools').register({'name': 'signal_probe', 'description': 'cancellation consumer',
        'parameters': {'type': 'object', 'properties': {}}, 'execute': execute,
        'output': {'schema': {'type': 'string'}, 'render': lambda args, value: [{'type': 'text', 'text': value}]}})
    try:
        handle.agent.followup('first turn')
        await asyncio.wait_for(ready.wait(), 3)
        initially_active = not signals[0].aborted
        handle.agent.cancel(cause)
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        handle.agent.followup('next turn')
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        output['tools'] = {'signalCount': len(signals), 'initiallyActive': initially_active,
            'firstAborted': signals[0].aborted, 'reason': signals[0].reason, 'notifications': notifications,
            'nextDistinct': signals[1] is not signals[0], 'nextActive': not signals[1].aborted,
            'modelRequests': len(model.requests), 'turnReasons': turn_reasons(handle.agent)}
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()
    ctx, model, handle = await harness()
    initial = True
    async def admission(payload, next_fn):
        nonlocal initial
        if not initial:
            return await next_fn()
        initial = False
        handle.agent.cancel(cause)
        raise RuntimeError('controlled failure after cancellation')
    handle.agent.ctx.on('agent/pre-step', admission)
    try:
        handle.agent.followup('cancelled admission')
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        handle.agent.followup('next admitted turn')
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        output['admission'] = {'status': handle.agent.status, 'modelRequests': len(model.requests),
                               'turnReasons': turn_reasons(handle.agent)}
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()
    ctx, model, handle = await harness(queued=True)
    queued_signals, queued_ready, release = [], asyncio.Event(), asyncio.Event()
    async def queued_execute(args, execution):
        queued_signals.append(execution.signal)
        if len(queued_signals) == 1:
            queued_ready.set()
            await release.wait()
        return 'queued tool consumed'
    ctx.get('tools').register({'name': 'queued_probe', 'description': 'queued consumer',
        'parameters': {'type': 'object', 'properties': {}}, 'execute': queued_execute,
        'output': {'schema': {'type': 'string'}, 'render': lambda args, value: [{'type': 'text', 'text': value}]}})
    try:
        handle.agent.followup('first queued turn')
        await asyncio.wait_for(queued_ready.wait(), 3)
        handle.agent.followup('second queued turn')
        release.set()
        await asyncio.wait_for(handle.agent.when_idle(), 3)
        output['queued'] = {'signalCount': len(queued_signals), 'sameSignal': queued_signals[0] is queued_signals[1],
            'active': all(not signal.aborted for signal in queued_signals), 'modelRequests': len(model.requests),
            'turnReasons': turn_reasons(handle.agent)}
    finally:
        release.set()
        await handle.dispose()
        await ctx.fiber.dispose()
    return output


if __name__ == '__main__':
    Path(sys.argv[1]).write_text(json.dumps(asyncio.run(observations()), ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
