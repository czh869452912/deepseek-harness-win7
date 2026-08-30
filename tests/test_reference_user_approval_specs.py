
import pytest
from dsh.cordis.context import Context
from dsh.core.agent import Agent, AgentPlugin
from dsh.core.session import Session, SessionStore, SessionPlugin
from dsh.interaction.user_approval import (
    ApprovalService,
    UserApprovalPlugin,
    effective_approval_policy,
    set_approval_policy,
)


def fake_agent(seed=None):
    if seed is None:
        seed = [{'type': 'turn/start', 'seq': 0, 'time': 100, 'data': {'turn': 1}}]
    appended = []

    class DummySession:
        def __init__(self):
            self.events = list(seed)

        def append(self, etype, data):
            ev = {'type': etype, 'data': data, 'seq': len(self.events), 'time': 100}
            appended.append(ev)
            self.events.append(ev)
            return ev

    session = DummySession()
    agent = Agent(agent_id='test-agent', session=session)
    return agent, appended


@pytest.mark.asyncio
async def test_throws_outside_open_turn():
    ctx = Context()
    svc = ApprovalService(ctx)
    agent, _ = fake_agent(seed=[])
    with pytest.raises(RuntimeError, match='outside an open turn'):
        await svc.request({'agent': agent, 'toolName': 'echo'})


@pytest.mark.asyncio
async def test_fails_closed_to_unavailable_when_nobody_listens():
    ctx = Context()
    svc = ApprovalService(ctx)
    agent, appended = fake_agent()
    outcome = await svc.request({'agent': agent, 'toolName': 'echo', 'callId': 'call-1', 'reason': 'hook says ask'})
    assert outcome == 'unavailable'
    assert len(appended) == 2
    assert appended[0]['type'] == 'approval/asked'
    assert appended[1]['type'] == 'approval/decided'
    assert appended[0]['data']['id'] == appended[1]['data']['id']
    assert appended[1]['data']['outcome'] == 'unavailable'


@pytest.mark.asyncio
async def test_answers_via_waterfall_listener():
    ctx = Context()
    svc = ApprovalService(ctx)
    ctx.on('approval/request', lambda req, next_fn=None: 'allowed-once')
    agent, appended = fake_agent()
    outcome = await svc.request({'agent': agent, 'toolName': 'scoped-tool'})
    assert outcome == 'allowed-once'
    assert appended[1]['data']['outcome'] == 'allowed-once'


@pytest.mark.asyncio
async def test_never_policy_rejects_without_consulting_answerer():
    ctx = Context()
    svc = ApprovalService(ctx, {'policy': 'never'})
    consulted = []
    ctx.on('approval/request', lambda req, next_fn=None: consulted.append(True) or 'allowed-once')
    agent, appended = fake_agent()
    outcome = await svc.request({'agent': agent, 'toolName': 'bash'})
    assert outcome == 'rejected'
    assert len(consulted) == 0
    assert appended[1]['data']['outcome'] == 'rejected'


def test_approval_policy_folding_and_rejection():
    agent, _ = fake_agent(seed=[{'type': 'turn/start', 'seq': 0, 'time': 100, 'data': {'turn': 1}}])
    session = agent.session
    assert effective_approval_policy(session.events) is None

    set_approval_policy(session, 'never')
    assert effective_approval_policy(session.events) == 'never'

    set_approval_policy(session, 'ask')
    assert effective_approval_policy(session.events) == 'ask'

    with pytest.raises(TypeError, match='approval policy must be one of'):
        set_approval_policy(session, 'invalid_policy')
