import asyncio

import pytest

from dsh.compaction.engine import CompactionEngine, ManualCompactionError, select_compactable_range
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentOptions
from dsh.core.session import Session
from dsh.llm.token_meter import TokenMeter


def setup(stream):
    ctx = Context()
    ctx.set_service('token_meter', TokenMeter(ctx))
    ctx.set_service('llm', type('Llm', (), {'stream': staticmethod(stream)})())
    session = Session(session_id='compact-transaction', ctx=ctx)
    session.append_user_message('important facts ' * 300)
    session.append_user_message('recent question')
    engine = CompactionEngine(ctx=ctx)
    agent = Agent(session, options=AgentOptions(provider='test', model='model'), ctx=ctx)
    return ctx, session, engine, agent


async def good(request):
    yield {'type': 'text-delta', 'index': 0, 'text': 'Keep the important facts.'}
    yield {'type': 'finish', 'reason': {'kind': 'stop'}}


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['error', 'aborted', 'max-tokens', 'empty', 'large', 'image'])
async def test_bad_summaries_close_bracket_without_replacing_history(failure):
    async def stream(request):
        if failure == 'image':
            yield {'type': 'block-end', 'index': 0, 'block': {'type': 'image', 'attachment': {}}}
        elif failure != 'empty':
            yield {'type': 'text-delta', 'index': 0, 'text': 'x' * 10000 if failure == 'large' else 'partial'}
        yield {'type': 'finish', 'reason': {'kind': failure if failure in ('error', 'aborted', 'max-tokens') else 'stop'}}
    ctx, session, engine, agent = setup(stream)
    with pytest.raises(ManualCompactionError) as error:
        await engine.compact_region(session, 0, 0, agent=agent, manual=True)
    assert error.value.code == 'summary'
    assert session.surface.nodes == [0, 1]
    assert [e['type'] for e in session.events[2:]] == ['compaction/start', 'compaction/end']
    await ctx.fiber.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize('manual', [True, False])
async def test_surface_stability_and_lock_during_summary(manual):
    entered, release = asyncio.Event(), asyncio.Event()
    async def stream(request):
        entered.set()
        await release.wait()
        async for item in good(request):
            yield item
    ctx, session, engine, agent = setup(stream)
    if not manual:
        session.append('turn/start', {'turn': 1})
    pending = asyncio.create_task(engine.compact_region(session, 0, 0, agent=agent, manual=manual))
    await entered.wait()
    with pytest.raises(ManualCompactionError) as error:
        await engine.compact_region(session, 0, 0, agent=agent, manual=manual)
    assert error.value.code == 'busy'
    session.append_user_message('new outside selected span')
    release.set()
    if manual:
        result = await pending
        assert result['shadowedSeqs'] == [0]
        assert 'new outside' in str(session.derive_messages())
    else:
        with pytest.raises(ManualCompactionError) as error:
            await pending
        assert error.value.code == 'changed'
        assert session.surface.replace_generation == 0
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_cancel_joins_summary_and_closes_transaction():
    entered, stopped = asyncio.Event(), asyncio.Event()
    async def stream(request):
        try:
            entered.set()
            await asyncio.Event().wait()
            yield None
        finally:
            stopped.set()
    ctx, session, engine, agent = setup(stream)
    signal = asyncio.Event()
    pending = asyncio.create_task(engine.compact_region(session, 0, 0, agent=agent, manual=True, signal=signal))
    await entered.wait()
    signal.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 2)
    assert stopped.is_set()
    assert session.events[-1]['type'] == 'compaction/end'
    assert session.surface.nodes == [0, 1]
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_failed_close_is_attempted_once_and_leaves_durable_lock():
    ctx, session, engine, agent = setup(good)
    append = session.append
    attempts = []
    def fail_close(kind, *args, **kwargs):
        if kind == 'compaction/end':
            attempts.append(kind)
            raise OSError('disk failure')
        return append(kind, *args, **kwargs)
    session.append = fail_close
    with pytest.raises(ManualCompactionError) as error:
        await engine.compact_region(session, 0, 0, agent=agent, manual=True)
    assert error.value.code == 'commit' and attempts == ['compaction/end']
    with pytest.raises(ManualCompactionError) as error:
        await engine.compact_region(session, session.surface.nodes[0], session.surface.nodes[0], agent=agent, manual=True)
    assert error.value.code == 'busy'
    await ctx.fiber.dispose()


@pytest.mark.asyncio
async def test_manual_maintenance_flush_and_provenance():
    ctx, session, engine, agent = setup(good)
    flushed = []
    async def flush():
        assert agent._phase_kind == 'maintenance'
        flushed.append(session.events[-1]['type'])
        return True
    session.flush = flush
    result = await engine.compact_now(agent, source_command_id='command-1')
    assert agent.status == 'idle' and flushed == ['compaction/end']
    record = session.events[result['summarySeq']]['data']
    assert record['llmStreamCall'] and record['provider'] == 'test'
    assert record['rawOutput'] == record['summary']
    checkpoint = session.events[session.surface.nodes[0]]
    assert checkpoint['data']['source'] == dict(kind='plugin', plugin='compact', compactionId=result['compactionId'], sourceCommandId='command-1')
    await ctx.fiber.dispose()


def test_selection_rejects_stale_measurement_and_retains_entire_tool_pair():
    session = Session(session_id='pair')
    session.append_user_message('old')
    session.append_assistant_message({'role': 'assistant', 'content': [dict(type='tool-call', id='a', name='read', arguments={})]})
    session.append('tool/result', {'message': {'role': 'tool', 'content': [], 'toolCallId': 'a'}}, surface_op='append')
    measured = {'nodes': [dict(seq=seq, tokens=10) for seq in session.surface.nodes]}
    assert select_compactable_range(session, measured, retain_tokens=0) == dict(start=0, end=0)
    session.append_user_message('new')
    with pytest.raises(ValueError, match='surface'):
        select_compactable_range(session, measured, retain_tokens=0)
