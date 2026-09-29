import pytest

from dsh.diagnostics.invariants import InvariantRegistry, InvariantError
from dsh.diagnostics.spine_invariants import AgentInvariant, ScopeInvariant, AgentLoopInvariant
from dsh.core.session.invariant import SessionInvariantPlugin
from dsh.llm.agent_request import mark_agent_loop_request
from test_subagent_in_process import setup


@pytest.mark.asyncio
async def test_real_agent_turn_reconstructs_and_scope_rejects_foreign_dispatch():
    ctx, model, owner = await setup()
    await ctx.plugin(InvariantRegistry)
    fibers = [await ctx.plugin(plugin) for plugin in (AgentInvariant, ScopeInvariant, AgentLoopInvariant, SessionInvariantPlugin)]
    try:
        owner.agent.followup('hello')
        await owner.agent.when_idle()
        assert model.requests and any(e['type'] == 'assistant/message' for e in owner.agent.session.events)
        with pytest.raises(InvariantError, match='scope carrier'):
            ctx.emit('agent/status', dict(agent=owner.agent, status='running'))
        other = await ctx.get('agents').create('other-invariant')
        try:
            local, foreign = [], []
            owner.agent.ctx.on('agent/pre-step', lambda payload, next_fn: local.append(payload['agent']) or next_fn())
            other.agent.ctx.on('agent/pre-step', lambda payload, next_fn: foreign.append(payload['agent']) or next_fn())
            owner.agent.followup('scoped followup')
            await owner.agent.when_idle()
            assert local == [owner.agent] and foreign == []
            with pytest.raises(InvariantError, match='different subject'):
                other.agent.ctx.emit('agent/status', dict(agent=owner.agent, status='running'))
        finally:
            await other.dispose()
        owner.agent.ctx.emit('agent/status', dict(agent=owner.agent, status='running'))
        with pytest.raises(InvariantError, match='repeated running'):
            owner.agent.ctx.emit('agent/status', dict(agent=owner.agent, status='running'))
        bad = mark_agent_loop_request(dict(sessionId=owner.agent.id, messages=[], model='fixture'))
        with pytest.raises(InvariantError, match='durable derivation'):
            await ctx.waterfall('llm/stream', bad, lambda: None)
        for fiber in fibers:
            await fiber.dispose()
        assert not ctx.get('invariants').registrations
    finally:
        await owner.dispose()
        await ctx.fiber.dispose()


def test_main_request_snapshot_is_deeply_immutable_and_detached():
    original = dict(messages=[dict(role='user', content=[dict(type='text', text='before')])])
    frozen = mark_agent_loop_request(original)
    original['messages'][0]['content'][0]['text'] = 'after'
    assert frozen['messages'][0]['content'][0]['text'] == 'before'
    with pytest.raises(TypeError):
        frozen['messages'].append({})
    with pytest.raises(TypeError):
        frozen['messages'][0]['content'][0]['text'] = 'mutated'
