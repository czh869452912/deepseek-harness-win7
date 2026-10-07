from dsh.core.system_prompt import SystemPrompt as SourceToolsPrompt
import asyncio

import pytest

from dsh.cordis.context import Context
from dsh.core.agent import AgentPlugin
from dsh.core.agent_loop import AgentLoopPlugin
from dsh.core.session import SessionPlugin
from dsh.core.tool_calls import execute_tool_calls
from dsh.core.tools import ToolsPlugin


async def harness(identity):
    ctx = Context()
    await ctx.plugin(SessionPlugin)
    await ctx.plugin(SourceToolsPrompt)
    await ctx.plugin(ToolsPlugin)
    await ctx.plugin(AgentPlugin)
    await ctx.plugin(AgentLoopPlugin)
    handle = await ctx.get('agents').create(session_id=identity)
    return ctx, handle, handle.agent


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected', [
    ('pre-error', ['pre', 'finish', 'notify']),
    ('around-error', ['pre', 'around', 'finish', 'notify']),
    ('pre-deny', ['pre', 'post', 'finish', 'notify']),
    ('success', ['pre', 'around', 'body', 'post', 'finish', 'notify']),
])
async def test_ordered_scheduler_finishes_actual_prepared_and_dispatched_results(mode, expected):
    ctx, handle, agent = await harness(mode)
    phases = []

    def body(arguments, execution):
        phases.append('body')
        return 'body result'

    def finish(execution, result):
        phases.append('finish')
        return [{'type': 'text', 'text': 'finalized'}]

    def pre(execution, next_fn):
        phases.append('pre')
        if mode == 'pre-error':
            raise RuntimeError('pre failed')
        return {'kind': 'deny', 'reason': 'denied'} if mode == 'pre-deny' else next_fn()

    def around(execution, next_fn):
        phases.append('around')
        if mode == 'around-error':
            raise RuntimeError('around failed')
        return next_fn()

    def post(execution, result, next_fn):
        phases.append('post')
        return next_fn()

    ctx.get('tools').register({
        'name': 'probe', 'description': 'probe', 'parameters': {}, 'execute': body,
        'output': {'schema': {'type': 'string'}, 'render': lambda arguments, value: [
            {'type': 'text', 'text': value}]},
        'finalizeContent': finish,
    })
    ctx.on('tools/pre-execute', pre)
    ctx.on('tools/execute', around)
    ctx.on('tools/post-execute', post)
    ctx.on('tools/result', lambda *arguments: phases.append('notify'))
    try:
        await execute_tool_calls(agent.ctx, agent, 1, 1, [
            {'type': 'tool-call', 'id': 'c1', 'name': 'probe', 'arguments': '{}'},
        ], asyncio.Event())
        assert phases == expected
        results = [event for event in agent.session.events if event['type'] == 'tool/result']
        assert len(results) == 1
        result = results[0]['data']['message']['content'][0]
        assert result['content'] == [{'type': 'text', 'text': 'finalized'}]
        assert result['isError'] is (mode != 'success')
    finally:
        await handle.dispose()
        await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('sibling_before_prepare', [False, True])
async def test_scheduler_preserves_first_failure_and_drains_without_late_dispatch(sibling_before_prepare):
    ctx, handle, agent = await harness('failure-during-prepare')
    entered, release_prepare = asyncio.Event(), asyncio.Event()
    first_observed, sibling_observed = asyncio.Event(), asyncio.Event()
    loop = asyncio.get_running_loop()
    release_first, release_sibling = loop.create_future(), loop.create_future()
    tools = ctx.get('tools')
    dispatches = []
    tools.register({
        'name': 'probe', 'description': 'probe', 'parameters': {},
        'isConcurrencySafe': lambda arguments: True,
        'execute': lambda arguments, execution: 'unused',
        'output': {'schema': {'type': 'string'}, 'render': lambda arguments, value: [
            {'type': 'text', 'text': value}]},
    })
    original_prepare, original_dispatch = tools.prepare, tools.dispatch

    async def prepare(execution):
        prepared = await original_prepare(execution)
        if execution.call_id == 'c3':
            entered.set()
            await release_prepare.wait()
        return prepared

    async def dispatch(execution):
        dispatches.append(execution.call_id)
        if execution.call_id in ('c1', 'c2'):
            future = release_first if execution.call_id == 'c1' else release_sibling
            observed = first_observed if execution.call_id == 'c1' else sibling_observed
            try:
                return await future
            finally:
                loop.call_soon(observed.set)
        return await original_dispatch(execution)

    tools.prepare, tools.dispatch = prepare, dispatch
    first_failure, sibling_failure = RuntimeError('first failure'), RuntimeError('sibling failure')
    pending = asyncio.create_task(execute_tool_calls(agent.ctx, agent, 1, 1, [
        {'type': 'tool-call', 'id': identity, 'name': 'probe', 'arguments': '{}'}
        for identity in ('c1', 'c2', 'c3')
    ], asyncio.Event(), max_parallel=3))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        release_first.set_exception(first_failure)
        await asyncio.wait_for(first_observed.wait(), 5)
        if sibling_before_prepare:
            release_sibling.set_exception(sibling_failure)
            await asyncio.wait_for(sibling_observed.wait(), 5)
        assert not pending.done()
        release_prepare.set()
        if not sibling_before_prepare:
            release_sibling.set_exception(sibling_failure)
        with pytest.raises(RuntimeError) as failed:
            await asyncio.wait_for(pending, 5)
        assert failed.value is first_failure
        assert dispatches == ['c1', 'c2']
        assert [event['data']['callId'] for event in agent.session.events
                if event['type'] == 'tool/call'] == ['c1', 'c2', 'c3']
        assert not [event for event in agent.session.events if event['type'] == 'tool/result']
        assert release_first.done() and release_sibling.done()
    finally:
        release_prepare.set()
        for future in (release_first, release_sibling):
            if not future.done():
                future.set_result(None)
        await asyncio.gather(pending, return_exceptions=True)
        await handle.dispose()
        await ctx.fiber.dispose()
