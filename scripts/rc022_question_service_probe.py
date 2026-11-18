"""Current userQuestions service and model tool against unchanged Source."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import rc022_events_probe as probe


async def observe():
    from dsh.cordis import Context
    from dsh.cordis.plugin import Plugin
    from dsh.core.abort import AbortController
    from dsh.core.session.current_session import CurrentSession
    from dsh.interaction.user_questions_current import CurrentUserQuestionService
    from dsh.interaction.tool_ask_user_current import CurrentToolAskUserPlugin
    from dsh.session.projections import SessionProjectionRegistry
    class Projections(Plugin):
        def apply(self, ctx):
            SessionProjectionRegistry(ctx, 4)
    ctx = Context()
    await ctx.plugin(Projections)
    session = CurrentSession.create('question-probe', format_version=4)
    agent = NS(id='agent-1', session=session, inbox=NS(nextTurn=[], nextStep=[]))
    agent.steer = agent.inbox.nextTurn.append
    definitions = []
    ctx.set_service('agents', NS(get=lambda identity: agent if identity == agent.id else None))
    ctx.set_service('tools', NS(register=lambda definition: (definitions.append(definition), lambda: None)[1]))
    owner = await ctx.plugin(CurrentUserQuestionService)
    service = ctx.userQuestions
    rows = []
    q = dict(id='scope', question='Which scope?')
    request = dict(questions=[q], agent=agent)
    def row(name, **value):
        rows.append(dict(name=name, **value))
    def failure(error):
        return dict(code=getattr(error, 'code', None), message=getattr(error, 'message', str(error)))
    try:
        row('unattended', result=await service.askTimed(request, 'unattended', 5))
        for value in (0, True, 1.5, 2147483648):
            try:
                await service.askTimed(request, 'bad', value)
            except Exception as error:
                row('invalid-timeout', error=failure(error))
        task = asyncio.create_task(service.askTimed(request, 'held', 25))
        await asyncio.sleep(0)
        client = AbortController()
        stream = service.attachWait(agent, 'held', client.signal)
        frame = await stream.__anext__()
        await asyncio.sleep(0.04)
        row('held', range=0 <= frame['remainingMs'] <= 25, pending=not task.done())
        client.abort()
        await stream.aclose()
        row('disconnected', result=await task)
        release = ctx.on('user-questions/request', lambda *_: dict(answers=[dict(id='scope', selected=[])]))
        row('answered', result=await service.askTimed(request, 'answered', 1000))
        release()
        session.append('request/header', dict(header=dict(config=dict(provider='fixture', model='fixture'), tools=[dict(name='ask_user_question', description='Question', parameters=dict(properties=dict(timeout={})))]), reason='initial'))
        session.append('tool/call', dict(turn=1, step=1, callId='late', name='ask_user_question', arguments=json.dumps(dict(questions=[q]))))
        session.append('tool/result', dict(turn=1, step=1, message=dict(id='result-1', role='tool', toolCallId='late', content=[dict(type='text', text='{"pending":true}')], isError=False)), surface_op='append')
        batch = dict(answers=[dict(id='scope', selected=[], custom='Later')])
        row('late', accepted=service.answer(agent, 'late', batch))
        message = agent.inbox.nextTurn.pop()
        row('late-message', source=message['source'], payload=json.loads(message['content'][0]['text']))
        try:
            service.answer(agent, 'late', batch)
        except Exception as error:
            row('duplicate', error=failure(error))
        ctx.emit('agent/inbox/discarded', dict(agent=agent, message=message))
        service.answer(agent, 'late', batch)
        message = agent.inbox.nextTurn.pop()
        session.append('user/message', message, surface_op='append')
        row('admitted', accepted=service.answer(agent, 'late', batch), projection=service.projection.stateOf(session)['questions'])
        for mode in ('legacy', 'timed'):
            tool_owner = await ctx.plugin(CurrentToolAskUserPlugin, dict(mode=mode))
            definition = definitions[-1]
            row('tool-'+mode, description=definition['description'], parameters=definition['parameters'], output=definition['output']['schema'])
            if mode == 'timed':
                async def ask_timed(request, call_id, timeout):
                    row('tool-request', questions=request['questions'], waitMs=timeout, callId=call_id, sameAgent=request['agent'] is agent)
                    return dict(pending=True, callId=call_id)
                service.askTimed = ask_timed
                row('tool-result', result=await definition['execute'](dict(questions=[q]), NS(agent=agent, callId='tool-1', signal=None)))
            await tool_owner.dispose()
        await owner.dispose()
        row('unload', service=ctx.get('userQuestions') is not None,
            projection=ctx.sessionProjections.snapshot(session, ['userQuestions'])['values'])
        return json.loads(json.dumps(rows))
    finally:
        await ctx.fiber.dispose()


if __name__ == '__main__':
    probe.native = observe
    probe.main('rc022_question_service.mts', 'Actual current service registration/projection, finite/unattended/UI-claimed waits, disconnect/answer, late reply queue/discard/admission, exact tool schemas/results and reversible unload.',
        [Path(__file__).resolve(), *[ROOT / ('dsh/interaction/' + name + '.py') for name in
            ('user_questions_current', 'question_projection', 'question_wait', 'tool_ask_user_current')],
         *[ROOT / ('reference/packages/interaction/user-questions/src/' + name + '.ts') for name in ('index', 'projection', 'timed-wait')],
         *[ROOT / ('reference/packages/interaction/tool-ask-user/src/' + name + '.ts') for name in ('index', 'timed')]])
