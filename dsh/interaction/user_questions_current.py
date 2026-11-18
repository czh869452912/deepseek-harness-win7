"""Current userQuestions Remote service, foreground waits and durable replies."""
import asyncio
import math
from weakref import WeakKeyDictionary

from dsh.cordis.errors import ThrownValueError
from dsh.cordis.json_text import stringify_json
from dsh.cordis.schema import Schema
from dsh.core.abort import abort_reason_error
from dsh.core.scope import scope_target
from dsh.jobs.pump import field
from dsh.llm.message import create_user_message
from dsh.typert.remote import Remote, TypertRemoteService
from .question_projection import USER_QUESTION_PROJECTION
from .question_wait import TimedQuestionWait
from .user_questions import UserQuestionError, UserQuestionService


def aborted_question(cause=None):
    return UserQuestionError('ask_user_question was aborted before the user answered', 'ASK_ABORTED', cause)


class CurrentUserQuestionService(TypertRemoteService):
    Config = Schema.object({})

    def __init__(self, ctx, config=None):
        super().__init__(ctx, 'userQuestions')
        self.provider = None
        self.projection = None
        self.waits = {}
        self.queued_replies = WeakKeyDictionary()
        def dispose():
            for agent, calls in list(self.waits.values()):
                for wait in list(calls.values()):
                    wait.close(aborted_question())
            self.waits.clear()
        ctx.effect(lambda: dispose, label='userQuestions: foreground waits')
        ctx.on('agent/inbox/claimed', self._claimed, global_listener=True)
        ctx.on('agent/inbox/discarded', self._discarded, global_listener=True)
        ctx.on('session/event', self._session_event, global_listener=True)

    # Keep the Python answerer adapter; its registrations are owned by ctx.
    registerProvider = UserQuestionService.registerProvider
    register_provider = UserQuestionService.register_provider

    async def init(self):
        async def bind(ctx):
            self.projection = await ctx.sessionProjections.register(USER_QUESTION_PROJECTION)
            def unbind():
                self.projection = None
            return unbind
        binding = self.ctx.inject(['sessionProjections'], bind)
        if self.ctx.get('sessionProjections') is not None:
            await binding

    def _release_reply(self, session, call_id, message_id):
        calls = self.queued_replies.get(session)
        if calls is not None and calls.get(call_id, {}).get('messageId') == message_id:
            del calls[call_id]

    def _claimed(self, payload):
        agent, message, turn = field(payload, 'agent'), field(payload, 'message'), field(payload, 'turn')
        source = field(message, 'source')
        if source['kind'] != 'user-question-reply':
            return
        calls = self.queued_replies.setdefault(agent.session, {})
        reply = calls.get(source['callId'])
        if reply is None:
            calls[source['callId']] = dict(messageId=field(message, 'id'), claimedTurn=turn)
        elif reply['messageId'] == field(message, 'id'):
            reply['claimedTurn'] = turn

    def _discarded(self, payload):
        agent, message = field(payload, 'agent'), field(payload, 'message')
        source = field(message, 'source')
        if source['kind'] == 'user-question-reply':
            self._release_reply(agent.session, source['callId'], field(message, 'id'))

    def _session_event(self, session, event):
        data = event['data']
        if event['type'] == 'user/message' and data['source']['kind'] == 'user-question-reply':
            self._release_reply(session, data['source']['callId'], data['id'])
        elif event['type'] == 'turn/end':
            calls = self.queued_replies.get(session)
            if calls is not None:
                for call_id, reply in list(calls.items()):
                    if reply.get('claimedTurn') == data['turn']:
                        del calls[call_id]

    def _assert_live_root(self, agent):
        agents = self.ctx.get('agents')
        if agents is None or agents.get(agent.id) is not agent:
            raise UserQuestionError('human interaction requires the exact live calling agent when an agent is supplied', 'CALLER_NOT_LIVE')
        if field(agent.session.header, 'origin') == 'subagent':
            raise UserQuestionError('human interaction is unavailable while the calling agent is owned by another live agent; '
                "include the unresolved question or decision in the child agent's final result", 'DELEGATED_CALLER')

    @Remote
    def answer(self, agent, callId, answer):
        self._assert_live_root(agent)
        active = self.projection.stateOf(agent.session)['questions']['active'] if self.projection is not None else []
        question = next((item for item in active if item['state'] == 'continued' and item['callId'] == callId), None)
        if question is None:
            return False
        queued = self.queued_replies.get(agent.session, {})
        messages = field(agent.inbox, 'nextTurn') + field(agent.inbox, 'nextStep')
        if callId in queued or any(field(message, 'source').get('kind') == 'user-question-reply'
                and field(message, 'source').get('callId') == callId for message in messages):
            raise UserQuestionError('a reply is already queued for this question', 'REPLY_QUEUED')
        answers = answer['answers']
        answered = {item['id'] for item in answers}
        if len(answered) != len(answers) or len(question['questions']) != len(answers) or any(item['id'] not in answered for item in question['questions']):
            raise UserQuestionError('the answer batch for %s must name each of its %s questions exactly once' % (callId, len(question['questions'])), 'BAD_ANSWER')
        message = create_user_message(dict(source=dict(kind='user-question-reply', callId=callId, outcome='answered'),
            content=[dict(type='text', text=stringify_json(dict(kind='answer_to_pending_question', tool='ask_user_question',
                callId=callId, questions=question['questions'], answers=answers)))]))
        queued[callId] = dict(messageId=message['id'])
        self.queued_replies[agent.session] = queued
        try:
            agent.steer(message)
        except BaseException:
            self._release_reply(agent.session, callId, message['id'])
            raise
        return True

    @Remote(dict(mode='stream'))
    async def attachWait(self, agent, callId, signal):
        self._assert_live_root(agent)
        entry = self.waits.get(id(agent))
        wait = entry[1].get(callId) if entry is not None and entry[0] is agent else None
        if wait is not None:
            async for frame in wait.attach(signal):
                yield frame

    async def askTimed(self, request, callId, timeoutMs):
        if type(timeoutMs) not in (int, float) or not math.isfinite(timeoutMs) or int(timeoutMs) != timeoutMs or not 1 <= timeoutMs <= 2147483647:
            raise UserQuestionError('timeout must fit a positive platform timer', 'BAD_TIMEOUT')
        agent = request['agent']
        self._assert_live_root(agent)
        entry = self.waits.setdefault(id(agent), (agent, {}))
        calls = entry[1]
        if callId in calls:
            raise UserQuestionError('the question call already has a foreground wait', 'DUPLICATE_WAIT')
        wait = TimedQuestionWait(TimedQuestionWait.now() + timeoutMs, request.get('signal'),
            UserQuestionError('ask_user_question timed out before the user answered', 'ASK_TIMED_OUT'))
        calls[callId] = wait
        try:
            try:
                return await self.ask(dict(request, signal=wait.signal, wait=dict(callId=callId, timed=True)))
            except Exception as error:
                if wait.signal.aborted:
                    raise abort_reason_error(wait.signal)
                if isinstance(error, UserQuestionError) and error.code == 'NO_PROVIDER':
                    await asyncio.shield(wait.done)
                    raise abort_reason_error(wait.signal)
                raise
        except Exception as error:
            if isinstance(error, UserQuestionError) and error.code == 'ASK_TIMED_OUT':
                return dict(pending=True, callId=callId)
            if wait.signal.aborted:
                raise aborted_question(error)
            raise
        finally:
            wait.close(aborted_question())
            calls.pop(callId, None)
            if not calls:
                self.waits.pop(id(agent), None)

    async def ask(self, request):
        signal, questions, agent = request.get('signal'), request['questions'], request.get('agent')
        if signal is not None and signal.aborted:
            raise aborted_question()
        if not questions:
            raise UserQuestionError('ask_user_question requires at least one question', 'EMPTY_QUESTIONS')
        if agent is not None:
            self._assert_live_root(agent)
        for question in questions:
            intent = question.get('intent')
            if intent is None:
                continue
            approval = intent['kind'] == 'approval'
            labels = [intent['approve'], intent['reject']] + ([intent['always']] if 'always' in intent else []) if approval else [intent['approve']]
            options = question.get('options', [])
            for label in labels:
                if not any(option['label'] == label for option in options):
                    role = 'action' if approval else 'approve'
                    raise UserQuestionError('question %s declares intent %s whose %s label %s names none of its options' %
                        (question['id'], intent['kind'], role, stringify_json(label)), 'BAD_INTENT')
            if 'detail' not in question:
                detail = 'scope detail it requires' if approval else 'detail it reviews'
                raise UserQuestionError('question %s declares intent %s without the %s' % (question['id'], intent['kind'], detail), 'BAD_INTENT')
            if approval:
                message = None
                if len(questions) != 1:
                    message = 'approval presentation requires one question; received %s' % len(questions)
                elif question.get('multiSelect') is True:
                    message = 'approval question %s does not support multiSelect' % question['id']
                elif 'wait' in request:
                    message = 'approval question %s requires a blocking request without wait' % question['id']
                elif len(set(labels)) != len(labels):
                    message = 'approval question %s requires distinct action labels; received %s' % (question['id'], stringify_json(labels))
                elif len(options) != len(labels):
                    message = 'approval question %s requires %s options matching its actions; received %s' % (question['id'], len(labels), len(options))
                if message is not None:
                    raise UserQuestionError(message, 'BAD_INTENT')
        async def no_answerer(*_):
            raise UserQuestionError('no user-questions answerer accepted the request', 'NO_PROVIDER')
        try:
            if agent is None:
                return await self.ctx.waterfall('user-questions/request', request, no_answerer)
            return await self.ctx.waterfall('user-questions/request', request, no_answerer, caller_ctx=scope_target(agent, agent))
        except Exception as error:
            reason = error.value if isinstance(error, ThrownValueError) else error
            if isinstance(reason, UserQuestionError):
                raise reason
            if isinstance(reason, dict) and reason.get('name') == 'UserQuestionError' and isinstance(reason.get('message'), str) and isinstance(reason.get('code'), str):
                raise UserQuestionError(reason['message'], reason['code'], error)
            if signal is not None and signal.aborted:
                raise aborted_question(error)
            raise
