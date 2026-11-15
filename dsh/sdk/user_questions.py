"""SDK-owned user-question forwarding, strict host answers and cancellation."""
import uuid

from dsh.core.abort import AbortController
from dsh.core.cancellation import subscribe_abort
from dsh.interaction.user_questions import UserQuestionError


def joined_signals(*signals):
    controller = AbortController()
    removers = [subscribe_abort(signal, lambda reason: controller.abort(reason)) for signal in signals if signal is not None]
    def detach():
        for remove in removers:
            remove()
    return controller.signal, detach


def parse_host_answer(value, question_ids):
    def bad():
        raise UserQuestionError('SDK host must answer each question id exactly once with selected labels and optional custom text', 'BAD_ANSWER')
    if isinstance(value, dict) and 'cancelled' in value:
        if value['cancelled'] is not True or len(value) != 1:
            bad()
        raise UserQuestionError('The user dismissed the SDK question', 'ASK_CANCELLED')
    if not isinstance(value, dict) or not isinstance(value.get('answers'), list):
        bad()
    answers = []
    for answer in value['answers']:
        if (not isinstance(answer, dict) or not isinstance(answer.get('id'), str)
                or not isinstance(answer.get('selected'), list) or any(not isinstance(label, str) for label in answer['selected'])
                or ('custom' in answer and not isinstance(answer['custom'], str))):
            bad()
        selected = dict(id=answer['id'], selected=answer['selected'])
        if 'custom' in answer:
            selected['custom'] = answer['custom']
        answers.append(selected)
    ids = {answer['id'] for answer in answers}
    if len(ids) != len(answers) or len(answers) != len(question_ids) or any(identity not in ids for identity in question_ids):
        bad()
    return dict(answers=answers)


class SdkUserQuestionBridge:
    def __init__(self, ctx, transport, owns_agent):
        self.ctx, self.transport, self.owns_agent = ctx, transport, owns_agent
        self.enabled = False
        self.shutdown = AbortController()
        self.unregister = ctx.on('user-questions/request', self.answer)

    async def answer(self, request, next_fn):
        agent = request.get('agent')
        if not self.enabled or agent is None or not self.owns_agent(agent):
            return await next_fn()
        return await self.ask(request, str(agent.session.id))

    def close(self):
        self.enabled = False
        self.unregister()
        self.shutdown.abort(UserQuestionError('SDK server is shutting down', 'ASK_ABORTED'))

    async def ask(self, request, session_id):
        params = dict(requestId=str(uuid.uuid4()), sessionId=session_id, questions=request['questions'])
        signal, detach = joined_signals(request.get('signal'), self.shutdown.signal)
        def cancelled(_reason):
            try:
                self.transport.notify('user-question.cancelled', dict(requestId=params['requestId'], sessionId=session_id))
            except Exception as error:
                self.ctx.logger.warn('SDK question cancellation could not reach the host: ' + str(error))
        remove = lambda: None
        try:
            signal.throwIfAborted()
            remove = subscribe_abort(signal, cancelled)
            try:
                result = await self.transport.request('user-question/ask', params, signal)
                return parse_host_answer(result, [question['id'] for question in request['questions']])
            except Exception as error:
                if isinstance(error, UserQuestionError):
                    raise
                raise UserQuestionError('SDK user question was cancelled' if signal.aborted else 'SDK host could not answer the user question',
                                        'ASK_ABORTED' if signal.aborted else 'PROVIDER_ERROR', error) from error
        finally:
            remove()
            detach()
