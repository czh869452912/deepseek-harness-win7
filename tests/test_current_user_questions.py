import asyncio
import json
from types import SimpleNamespace as NS

import pytest
import pytest_asyncio

from dsh.cordis import Context
from dsh.cordis.plugin import Plugin
from dsh.core.abort import AbortController
from dsh.core.session.current_session import CurrentSession
from dsh.interaction.question_wait import TimedQuestionWait
from dsh.interaction.tool_ask_user_current import CurrentToolAskUserPlugin, validate_timeout, PENDING_NOTICE
from dsh.interaction.user_questions import UserQuestionError
from dsh.interaction.user_questions_current import CurrentUserQuestionService
from dsh.session.projections import SessionProjectionRegistry
from dsh.typert.remote import remote_methods


class Projections(Plugin):
    def apply(self, ctx):
        SessionProjectionRegistry(ctx, 4)


@pytest_asyncio.fixture
async def questions():
    ctx = Context()
    await ctx.plugin(Projections)
    session = CurrentSession.create('question-test', format_version=4)
    agent = NS(id='agent-1', session=session, inbox=NS(nextTurn=[], nextStep=[]))
    agent.steer = agent.inbox.nextTurn.append
    live = {agent.id: agent}
    ctx.set_service('agents', NS(get=live.get))
    owner = await ctx.plugin(CurrentUserQuestionService)
    try:
        yield ctx, ctx.userQuestions, agent, owner, live
    finally:
        await ctx.fiber.dispose()


def request(agent, **extra):
    return dict(questions=[dict(id='scope', question='Which scope?')], agent=agent, **extra)


def continued(agent, service):
    # Append real v4 Session records, rather than injecting projection state.
    agent.session.append('request/header', dict(header=dict(config=dict(provider='fixture', model='fixture'),
        tools=[dict(name='ask_user_question', description='Question', parameters=dict(properties=dict(timeout={})))]), reason='initial'))
    agent.session.append('tool/call', dict(turn=1, step=1, callId='call_1', name='ask_user_question',
        arguments=json.dumps(dict(questions=[dict(id='scope', question='Which scope?')]))))
    agent.session.append('tool/result', dict(turn=1, step=1, message=dict(id='result-1', role='tool', toolCallId='call_1',
        content=[dict(type='text', text='{"pending":true}')], isError=False)), surface_op='append')
    assert service.projection.stateOf(agent.session)['questions']['active'][0]['state'] == 'continued'


@pytest.mark.asyncio
async def test_current_questions_timeout_without_provider_and_disposal(questions):
    ctx, service, agent, owner, live = questions
    assert await service.askTimed(request(agent), 'call_1', 5) == dict(pending=True, callId='call_1')
    task = asyncio.create_task(service.askTimed(request(agent), 'call_2', 1000))
    await asyncio.sleep(0)
    await owner.dispose()
    with pytest.raises(UserQuestionError, match='aborted') as error:
        await task
    assert error.value.code == 'ASK_ABORTED'
    assert not service.waits


@pytest.mark.asyncio
async def test_current_questions_exact_live_identity_and_subagent_origin(questions):
    ctx, service, agent, _, live = questions
    answer = dict(answers=[dict(id='scope', selected=[])])
    ctx.on('user-questions/request', lambda *_: answer)
    assert await service.ask(request(agent)) == answer
    foreign = NS(**vars(agent))
    with pytest.raises(UserQuestionError) as error:
        await service.ask(request(foreign))
    assert error.value.code == 'CALLER_NOT_LIVE'
    agent.session = NS(header=dict(origin='subagent'))
    with pytest.raises(UserQuestionError) as error:
        await service.ask(request(agent))
    assert error.value.code == 'DELEGATED_CALLER'


@pytest.mark.asyncio
async def test_current_questions_late_reply_queue_ownership_and_admission(questions):
    ctx, service, agent, _, _ = questions
    continued(agent, service)
    answer = dict(answers=[dict(id='scope', selected=[], custom='Later answer')])
    with pytest.raises(UserQuestionError) as error:
        service.answer(agent, 'call_1', dict(answers=[]))
    assert error.value.code == 'BAD_ANSWER'
    assert service.answer(agent, 'call_1', answer)
    message = agent.inbox.nextTurn.pop()
    assert json.loads(message['content'][0]['text'])['kind'] == 'answer_to_pending_question'
    assert service.projection.stateOf(agent.session)['questions']['active']
    ctx.emit('agent/inbox/discarded', dict(agent=agent, message=dict(message, id='foreign')))
    with pytest.raises(UserQuestionError) as error:
        service.answer(agent, 'call_1', answer)
    assert error.value.code == 'REPLY_QUEUED'
    ctx.emit('agent/inbox/discarded', dict(agent=agent, message=message))
    assert service.answer(agent, 'call_1', answer)
    accepted = agent.inbox.nextTurn.pop()
    agent.session.append('user/message', accepted, surface_op='append')
    assert not service.answer(agent, 'call_1', answer)
    assert service.projection.stateOf(agent.session)['questions']['settled'][0]['answers'] == answer['answers']


@pytest.mark.asyncio
async def test_current_questions_client_claim_blocks_host_expiry_until_disconnect(questions):
    ctx, service, agent, _, _ = questions
    task = asyncio.create_task(service.askTimed(request(agent), 'call_1', 25))
    await asyncio.sleep(0)
    client = AbortController()
    stream = service.attachWait(agent, 'call_1', client.signal)
    assert (await stream.__anext__())['remainingMs'] <= 25
    await asyncio.sleep(0.04)
    assert not task.done()
    client.abort()
    await stream.aclose()
    assert await asyncio.wait_for(task, 0.5) == dict(pending=True, callId='call_1')
    assert not service.waits


@pytest.mark.asyncio
async def test_current_questions_parent_abort_and_duplicate_wait(questions):
    _, service, agent, _, _ = questions
    parent = AbortController()
    task = asyncio.create_task(service.askTimed(request(agent, signal=parent.signal), 'call_1', 1000))
    await asyncio.sleep(0)
    with pytest.raises(UserQuestionError) as error:
        await service.askTimed(request(agent), 'call_1', 10)
    assert error.value.code == 'DUPLICATE_WAIT'
    parent.abort(RuntimeError('parent stop'))
    with pytest.raises(UserQuestionError) as error:
        await task
    assert error.value.code == 'ASK_ABORTED'


@pytest.mark.asyncio
async def test_current_questions_remote_exports_and_serialized_timeout(questions):
    ctx, service, agent, _, _ = questions
    exports = {item['method']: item for item in remote_methods(service)}
    assert set(exports) == {'answer', 'attachWait'}
    assert exports['attachWait']['mode'] == 'stream'
    from dsh.cordis.errors import ThrownValueError
    def timeout(*_):
        raise ThrownValueError(dict(name='UserQuestionError', code='ASK_TIMED_OUT', message='client countdown expired'))
    ctx.on('user-questions/request', timeout)
    assert await service.askTimed(request(agent), 'call_1', 1000) == dict(pending=True, callId='call_1')


@pytest.mark.parametrize('timeout', [True, 0, -2, 1.5, float('nan'), float('inf'), 2147484, '120'])
def test_current_question_tool_rejects_invalid_seconds(timeout):
    with pytest.raises(ValueError, match='timeout must be -1 or a positive integer'):
        validate_timeout(timeout)


@pytest.mark.asyncio
async def test_current_question_tool_modes_and_pending_contract(questions):
    ctx, service, agent, _, _ = questions
    definitions = []
    ctx.set_service('tools', NS(register=lambda definition: (definitions.append(definition), lambda: None)[1]))
    owner = await ctx.plugin(CurrentToolAskUserPlugin, dict(mode='timed', timeout=120))
    definition = definitions[-1]
    assert 'timeout' in definition['parameters']['properties']
    assert 'skipped that question' in definition['description']
    seen = []
    async def pending(req, call_id, milliseconds):
        seen.append((req, call_id, milliseconds))
        return dict(pending=True, callId=call_id)
    service.askTimed = pending
    result = await definition['execute'](dict(questions=[dict(id='x', question='Q?')]), NS(agent=agent, callId='tool-1', signal=None))
    assert result == dict(pending=True, callId='tool-1', message=PENDING_NOTICE)
    assert seen[0][1:] == ('tool-1', 120000)
    with pytest.raises(ValueError, match='must be unique'):
        await definition['execute'](dict(questions=[dict(id='x', question='A?'), dict(id='x', question='B?')]))
    await owner.dispose()
    await ctx.plugin(CurrentToolAskUserPlugin)
    assert 'timeout' not in definitions[-1]['parameters']['properties']
