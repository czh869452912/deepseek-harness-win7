import asyncio
import pytest

from dsh.core.abort import AbortSignal
from test_subagent_in_process import setup


@pytest.mark.asyncio
async def test_actual_agent_model_tool_signal_preserves_abort_reason_and_next_turn_generation():
    ctx, model, parent = await setup()
    seen, notifications, ready = [], [], asyncio.Event()
    async def model_stream(messages, tools=None, **kwargs):
        continuation = len(seen) >= 2
        delta = {'content': 'next turn completed'} if continuation else {'tool_calls': [
            {'index': 0, 'id': 'owned-signal-' + str(len(seen)), 'type': 'function', 'function': {'name': 'signal_probe', 'arguments': '{}'}}]}
        yield {'choices': [{'delta': delta, 'finish_reason': 'stop' if continuation else 'tool_calls'}]}
    model.chat_completion_stream = model_stream
    async def execute(args, execution):
        signal = execution.signal
        assert isinstance(signal, AbortSignal)
        seen.append(signal)
        def cancelled(event):
            notifications.append(event.target.reason)
        signal.addEventListener('abort', cancelled, {'once': True})
        try:
            if len(seen) == 1:
                ready.set()
                await signal.wait_aborted()
            return 'signal generation consumed'
        finally:
            signal.removeEventListener('abort', cancelled)
    ctx.get('tools').register({'name': 'signal_probe', 'description': 'actual cancellation consumer',
        'parameters': {'type': 'object', 'properties': {}}, 'execute': execute,
        'output': {'schema': {'type': 'string'}, 'render': lambda args, result: [{'type': 'text', 'text': result}]}})
    try:
        parent.agent.followup('first turn')
        await asyncio.wait_for(ready.wait(), 3)
        first = seen[0]
        assert first is parent.agent.signal and not first.aborted
        cause = {'kind': 'user', 'detail': 'actual cancellation reason'}
        parent.agent.cancel(cause)
        try:
            await asyncio.wait_for(parent.agent.when_idle(), 3)
        except asyncio.TimeoutError:
            pytest.fail(repr({'driverDone': parent.agent._driver_task.done(), 'signals': len(seen),
                              'recentEvents': parent.agent.session.events[-8:]}))
        assert first.aborted and first.reason is cause
        assert notifications == [cause]
        parent.agent.followup('next turn')
        try:
            await asyncio.wait_for(parent.agent.when_idle(), 3)
        except asyncio.TimeoutError:
            pytest.fail(repr({'driverDone': parent.agent._driver_task.done(), 'signals': len(seen),
                              'recentEvents': parent.agent.session.events[-8:]}))
        assert len(seen) == 2 and seen[1] is not first and not seen[1].aborted
        assert first.aborted and first.reason is cause and not first._listeners
        assert not seen[1]._listeners
    finally:
        await parent.dispose()
        await ctx.fiber.dispose()
