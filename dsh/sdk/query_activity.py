"""One native command's activity through quiescence and first goal outcome."""
import asyncio


class QueryActivity:
    def __init__(self, ctx, agent, transport, owns_invocation, signal, on_close):
        self.ctx, self.agent, self.transport = ctx, agent, transport
        self.owns_invocation, self.on_close = owns_invocation, on_close
        self.command_id = self.result = self.goal_id = self.goal_outcome = self.response = None
        self.closed = self.input = self.input_idle = self.goal_stopped = False
        self.turn_reason = 'completed'
        self.tasks = set()
        self.disposers = [ctx.on('session/event', self.session_event),
                          ctx.on('goal/activation-changed', self.activation_changed),
                          ctx.on('agent/status', self.status_changed),
                          ctx.on('agent/error', self.agent_error),
                          ctx.on('agent/disposed', self.agent_disposed)]
        def abort(_event):
            self.close()
        signal.addEventListener('abort', abort, dict(once=True))
        self.disposers.append(lambda: signal.removeEventListener('abort', abort))

    def session_event(self, session, event):
        if session is not self.agent.session:
            return
        own = self.result is None and self.owns_invocation()
        kind, data = event['type'], event['data']
        if own and kind == 'command/run' and self.command_id is None:
            self.command_id = data['commandId']
        if own and kind == 'agent/inbox/spliced' and any(message['source']['kind'] == 'user' for message in data['inserted']):
            self.input = True
        if kind == 'goal/change':
            if own and data['operation'] in ('create', 'resume'):
                self.goal_id = data['goal']['id']
            if data['operation'] == 'clear':
                if data['cleared']['id'] == self.goal_id and self.goal_outcome is None:
                    self.goal_outcome = 'aborted'
            elif data['goal']['id'] == self.goal_id and data['goal']['phase'] != 'active' and self.goal_outcome is None:
                self.goal_outcome = {'complete': 'completed', 'paused': 'aborted'}.get(data['goal']['phase'], 'error')
        if self.input or self.goal_id is not None:
            if kind == 'assistant/message':
                self.response = ''.join(block['text'] for block in data['message']['content'] if block['type'] == 'text')
            if kind == 'turn/end':
                self.turn_reason = data['reason']['kind']
        self.check()

    def activation_changed(self, change):
        goal = change.get('goal')
        if change['sessionId'] != self.agent.session.id or goal is None or goal['id'] != self.goal_id or goal.get('activation') != 'disarmed':
            return
        goals = self.ctx.get('goals')
        current = goals.get(self.agent) if goals is not None else None
        if current is not None and current['phase'] == 'active':
            self.goal_stopped = True
            self.check()

    def status_changed(self, info):
        if info['agent'] is self.agent:
            self.check()

    def agent_error(self, info):
        if info['agent'] is self.agent and (self.input or self.goal_id is not None):
            self.turn_reason = 'error'

    def agent_disposed(self, info):
        if info['agent'] is self.agent:
            self.finish('error', 'The Session Agent was disposed before the input finished.')

    def accept(self, execution):
        self.command_id, self.result = execution['commandId'], execution['result']
        if self.input:
            async def idle():
                await self.agent.whenIdle()
                if self.closed:
                    return
                self.input_idle = True
                self.check()
            task = asyncio.create_task(idle())
            self.tasks.add(task)
            def settled(done):
                self.tasks.discard(done)
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(settled)
        self.check()

    def goalUnavailable(self):
        if self.goal_id is not None:
            self.finish('error', 'The goal service was unloaded before the goal finished.')

    def close(self):
        if self.closed:
            return
        self.closed = True
        disposers, self.disposers = self.disposers, []
        for dispose in disposers:
            dispose()
        self.on_close(self)

    def check(self):
        if self.closed or self.result is None:
            return
        if self.result['kind'] == 'error':
            self.finish('error', self.result['text'])
            return
        if self.input and not self.input_idle:
            return
        if self.goal_id is not None:
            outcome = self.goal_outcome or ('error' if self.goal_stopped else None)
            if outcome is None or self.agent.status != 'idle':
                return
            reason = self.turn_reason if outcome == 'completed' else outcome
            failure = 'Goal execution stopped before reaching a terminal state.' if self.goal_outcome is None else ''
            self.finish(reason, self.response or failure)
            return
        if self.input:
            self.finish(self.turn_reason, self.response if self.response is not None else '')
            return
        self.finish('completed', self.result.get('text', ''))

    def finish(self, reason, response):
        if self.closed:
            return
        try:
            if self.command_id is not None:
                self.transport.notify('session.query.completed', dict(sessionId=self.agent.session.id,
                    commandId=self.command_id, finishReason=reason, finalResponse=response))
        finally:
            self.close()
