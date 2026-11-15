"""Passive execution state and revision-checked waits; never activate an Agent."""
import asyncio

from dsh.api.session_history_authorized import safe_integer, negative_zero
from dsh.api.session_history_current import not_found
from dsh.core.abort import AbortController
from dsh.core.timeout import deadline, timeout_of, MAX_TIMER_DELAY_MS
from dsh.typert.remote import RemoteError


class StateListener:
    def __init__(self, ctx, target, signal, read_state):
        signal.throwIfAborted()
        self.read_state = read_state
        self.cancellation = AbortController()
        self.signal = self.cancellation.signal
        self.cleanup, self.revision, self.closed = [], 0, False
        self.wake = asyncio.Event()
        def close(*_):
            self.cancellation.abort(signal.reason)
            self.dispose()
        signal.addEventListener('abort', close, dict(once=True))
        self.cleanup.append(lambda: signal.removeEventListener('abort', close))
        def notify(identity):
            if identity == target and not self.closed:
                self.revision += 1
                previous, self.wake = self.wake, asyncio.Event()
                previous.set()
        try:
            for event in ('session/event', 'session/created', 'session/disposed'):
                self.cleanup.append(ctx.on(event, lambda session, *_: notify(session.id), global_listener=True))
            for event in ('agent/status', 'agent/created', 'agent/disposed'):
                self.cleanup.append(ctx.on(event, lambda payload, *_: notify(payload['agent'].id), global_listener=True))
            self.cleanup.append(ctx.effect(lambda: self.dispose, 'session-controller.state-listener'))
        except BaseException:
            self.dispose()
            raise

    def isCurrent(self, revision):
        return not self.closed and revision == self.revision

    async def observeStates(self, refreshMs=None):
        last_revision = -1
        try:
            while not self.closed:
                if last_revision == self.revision:
                    if refreshMs is None:
                        await self.wake.wait()
                    else:
                        try:
                            await asyncio.wait_for(self.wake.wait(), refreshMs / 1000.0)
                        except asyncio.TimeoutError:
                            pass
                        if self.isCurrent(last_revision):
                            self.revision += 1
                            previous, self.wake = self.wake, asyncio.Event()
                            previous.set()
                if not self.isCurrent(self.revision):
                    return
                last_revision = self.revision
                state = await self.read_state(self.signal)
                if self.isCurrent(last_revision):
                    yield dict(state=state, revision=last_revision)
        finally:
            self.dispose()

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        self.cancellation.abort()
        self.wake.set()
        cleanup, self.cleanup = self.cleanup, []
        for dispose in reversed(cleanup):
            dispose()


def expired(signal, error):
    reason = timeout_of(signal, 'session/wait-timeout')
    if reason is None:
        return False
    current = error
    for _ in range(4):
        if not isinstance(current, BaseException):
            break
        cause = getattr(current, 'cause', None) or current.__cause__
        if current is reason or cause is reason:
            return True
        current = cause
    return error is reason


class SessionStateController:
    def __init__(self, ctx, history_controller):
        self.ctx, self.history_controller = ctx, history_controller

    def pendingInput(self, session_id):
        kinds = []
        for pending in self.ctx.get('typertGateway').getPendingRemoteEvents():
            if str(pending.get('agentId')) != session_id:
                continue
            event = pending['event']
            kind = 'approval' if event == 'approval/request' else 'question' if event == 'user-questions/request' else 'other'
            if kind not in kinds:
                kinds.append(kind)
        return kinds

    async def readState(self, session_id, signal, retried=False):
        signal.throwIfAborted()
        agent = self.ctx.get('agents').get(session_id)
        if agent is not None:
            if agent.session.header.cwd is None:
                raise not_found(dict(kind='session', sessionId=session_id))
            queue = []
            for messages, placement in ((agent.inbox.nextTurn, 'queued'), (agent.inbox.nextStep, None)):
                for message in messages:
                    source = message['source']
                    item = dict(id=message['id'], placement=placement or ('steering' if source['kind']=='user' else 'context'), content=message['content'])
                    if source['kind'] == 'user' and 'rpcId' in source:
                        item['rpcId'] = source['rpcId']
                    queue.append(item)
            return dict(cursor=agent.session.seq-1, active=True, running=agent.status=='running', queue=queue, pendingInput=self.pendingInput(agent.session.id))
        def read(observation):
            if not retried and observation.source == 'live':
                return None
            if observation.header.cwd is None:
                raise not_found(dict(kind='session', sessionId=session_id))
            return dict(cursor=observation.cursor, active=False, running=False, queue=None, pendingInput=self.pendingInput(observation.header.id))
        result = await self.history_controller.usingObservation(dict(sessionId=session_id, projection=False), signal, read)
        signal.throwIfAborted()
        return result if result is not None else await self.readState(session_id, signal, True)

    async def state(self, request, signal):
        return await self.readState(request['sessionId'], signal)

    def listen(self, session_id, signal):
        return StateListener(self.ctx, session_id, signal, lambda read_signal: self.readState(session_id, read_signal))

    async def observeState(self, request, signal):
        listener = self.listen(request['sessionId'], signal)
        states = listener.observeStates()
        try:
            async for observed in states:
                yield observed['state']
        finally:
            listener.dispose()
            await states.aclose()

    async def wait(self, request, signal):
        timeout_ms = request.get('timeoutMs', 30000)
        after_seq, maximum = request.get('afterSeq', -1), request.get('maxMessages', 50)
        if not safe_integer(after_seq) or after_seq < -1 or negative_zero(after_seq):
            raise RemoteError('gateway/bad-request', 'afterSeq must be an integer greater than or equal to -1', {})
        if not safe_integer(maximum) or maximum <= 0:
            raise RemoteError('gateway/bad-request', 'maxMessages must be a positive safe integer', {})
        if not safe_integer(timeout_ms) or not 0 < timeout_ms <= MAX_TIMER_DELAY_MS:
            raise RemoteError('gateway/bad-request', 'timeoutMs must be a positive supported timer delay', {})
        timer = deadline(signal, timeout_ms, 'session/wait-timeout')
        listener = states = next_state = None
        current, reason = None, 'timeout'
        try:
            listener = self.listen(request['sessionId'], timer.signal)
            states = listener.observeStates(1000)
            next_state = asyncio.ensure_future(states.__anext__())
            try:
                while True:
                    try:
                        observed = await asyncio.shield(next_state)
                    except StopAsyncIteration:
                        timer.signal.throwIfAborted()
                        raise RemoteError('session/observation-ended', 'Session observation ended before a stopping state', {}) from None
                    next_state = asyncio.ensure_future(states.__anext__())
                    # Observe immediate failure even if the preceding sample stops this wait.
                    next_state.add_done_callback(lambda task: None if task.cancelled() else task.exception())
                    if not listener.isCurrent(observed['revision']):
                        continue
                    current = observed['state']
                    if current['pendingInput']:
                        reason = 'input-required'
                        break
                    if current['running']:
                        continue
                    if not current['active']:
                        reason = 'idle'
                        break
                    agent = self.ctx.get('agents').get(request['sessionId'])
                    if agent is None or self.ctx.get('sessions').get(request['sessionId']) is not agent.session:
                        continue
                    idle = asyncio.ensure_future(agent.whenIdle())
                    try:
                        done, _ = await asyncio.wait((idle, next_state), return_when=asyncio.FIRST_COMPLETED)
                        if idle not in done:
                            # Re-raise state failures on the original demand in the next iteration.
                            continue
                        await idle
                    finally:
                        # This is an owned whenIdle observer, never the Agent driver.
                        if not idle.done():
                            idle.cancel()
                        await asyncio.gather(idle, return_exceptions=True)
                    if (not listener.isCurrent(observed['revision']) or self.ctx.get('agents').get(request['sessionId']) is not agent
                            or self.ctx.get('sessions').get(request['sessionId']) is not agent.session):
                        continue
                    reason = 'idle'
                    break
            except Exception as error:
                signal.throwIfAborted()
                if not expired(timer.signal, error):
                    raise
        finally:
            if listener is not None:
                listener.dispose()
            if next_state is not None:
                await asyncio.gather(next_state, return_exceptions=True)
            if states is not None:
                await states.aclose()
            timer.dispose()
        signal.throwIfAborted()
        if current is None:
            raise RemoteError('session/wait-timeout', 'No Session state arrived before the wait deadline', {})
        output = await self.history_controller.assistantOutput(request['sessionId'], after_seq, current['cursor'], maximum, signal)
        return dict(reason=reason, state=current, output=output)
