"""Capacity, durable-child serialization and suffix-bounded execution results."""
import asyncio
from contextlib import asynccontextmanager

from dsh.core.consumed_work import fold_consumed_work
from dsh.subagent.assistant_output_current import final_assistant_output
from dsh.subagent.errors import SubagentError
from dsh.subagent.tree import activation_agent


class ActivationPool:
    def __init__(self):
        self.slots = set()

    def reserve(self, capacity):
        if len(self.slots) >= capacity:
            raise SubagentError('subagent limit reached (active child limit: %s); wait for an existing child to finish '
                                'or complete this work with the current agents' % capacity,'ACTIVATION_LIMIT_REACHED')
        slot = object()
        self.slots.add(slot)
        return lambda: self.slots.discard(slot)


class ChildLock:
    def __init__(self):
        self.entries = {}

    @asynccontextmanager
    async def hold(self, sid):
        lock,count = self.entries.get(sid,(asyncio.Lock(),0))
        self.entries[sid] = (lock,count+1)
        try:
            await asyncio.sleep(0)
            async with lock:
                yield
        finally:
            _,count = self.entries[sid]
            if count == 1:
                self.entries.pop(sid)
            else:
                self.entries[sid] = (lock,count-1)

    def run(self, sid, operation):
        async def perform():
            async with self.hold(sid):
                return await operation()
        return asyncio.ensure_future(perform())


def require_local_activation(activation):
    if activation.kind == 'local':
        return activation
    raise SubagentError('subagent "%s" does not accept follow-up input' % activation.childId,'NOT_CONTINUABLE')


def epoch_stop_reason(events):
    work = fold_consumed_work(events)
    kind = work.end['data']['reason']['kind'] if work.end is not None else None
    if kind in (None,'completed'):
        return 'aborted' if work.dropped_unrun else 'completed'
    return {'max-tokens':'max-tokens','aborted':'aborted','interrupted':'aborted',
            'error':'error','blocked':'refusal'}.get(kind,'error')


def capture_local_result(activation):
    events = activation.handle.agent.session.snapshotEvents(activation.outputStart)
    result = dict(output=final_assistant_output(events) or [],
                  stopReason=epoch_stop_reason(events) if activation.failureAt is None else 'error')
    if activation.structured is not None:
        captured = activation.structured.captured()
        if captured is not None:
            result['structured'] = captured['value'] if isinstance(captured,dict) else captured.value
        elif result['stopReason'] == 'completed':
            result['stopReason'] = 'error'
    return result


def observe_local_failure(activation, wake):
    child = activation.handle.agent
    def error(payload):
        if payload['agent'] is child:
            activation.failureAt = child.session.seq
            wake()
    def event(session, event):
        if (session is child.session and event['type'] == 'turn/end' and activation.failureAt is not None
                and event['seq'] >= activation.failureAt):
            activation.failureAt = None
    child.ctx.on('agent/error',error)
    child.ctx.on('session/event',event)


activationAgent = activation_agent
requireLocalActivation = require_local_activation
captureLocalResult = capture_local_result
