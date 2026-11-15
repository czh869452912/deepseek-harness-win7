"""Current projected approval state and producer-owned policy notices."""
import uuid

from dsh.cordis.service import Service
from dsh.llm.message import create_user_message
from .user_approval import ApprovalService, set_approval_policy


class CurrentApprovalService(ApprovalService):
    inject = ['sessionProjections']

    def __init__(self, ctx, config=None):
        self.config, self._answers = config or {}, set()
        self.projection = None
        Service.__init__(self, ctx, 'approval')

    @staticmethod
    def _state(value):
        if (not isinstance(value, dict) or value.get('policy') not in (None, 'ask', 'never')
                or type(value.get('turnOpen')) is not bool):
            raise ValueError('invalid approval state')
        return dict(policy=value['policy'], turnOpen=value['turnOpen'])

    @staticmethod
    def _apply(state, event):
        kind = event['type']
        key = 'policy' if kind == 'approval/policy' else 'turnOpen'
        value = event['data']['policy'] if kind == 'approval/policy' else kind == 'turn/start'
        if kind not in ('approval/policy', 'turn/start', 'turn/end') or state[key] == value:
            return state
        return dict(state, **{key: value})

    async def init(self):
        self.projection = await self.ctx.sessionProjections.register(dict(key='approvalState', stateVersion=1,
            stateSchema=self._state, init=lambda *_:dict(policy=None, turnOpen=False), apply=self._apply))
        if self.ctx.fiber.uid is None:
            return
        def contribute(scope):
            scope.systemPrompt.context(dict(name='approval:policy', order=scope.systemPrompt.getContextOrder('APPROVAL_POLICY'), text=self._context_text))
        self.ctx.inject(['systemPrompt'], contribute)

    def override_of(self, session):
        return self.projection.stateOf(session)['policy']

    overrideOf = override_of

    def set_policy(self, agent, policy):
        previous = self.effective_policy(agent.session)
        if previous == policy:
            return
        set_approval_policy(agent.session, policy)
        names = dict(ask='ask the user for approval', never='never ask the user for approval')
        agent.inject(create_user_message(dict(source=dict(kind='user-approval'),content=[dict(type='text',
            text='The user changed the approval policy from "%s" to "%s".' % (names[previous], names[policy]))])))

    setPolicy = set_policy

    async def request(self, req):
        session = req['agent'].session
        if not self.projection.stateOf(session)['turnOpen']:
            raise RuntimeError('approval.request() outside an open turn: the approval/asked + approval/decided audit pair '
                'must be turn-enclosed (a bare event between turns is crash-tail garbage on reload). '
                'Ask from inside the turn that needs the decision.')
        identity = str(uuid.uuid4())
        asked = dict(id=identity, toolName=req['toolName'])
        for key in ('callId', 'reason'):
            if key in req:
                asked[key] = req[key]
        session.append('approval/asked', asked)
        outcome = await self.decide(req, session)
        session.append('approval/decided', dict(id=identity, outcome=outcome))
        return outcome
