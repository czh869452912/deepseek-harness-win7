"""Passive Session notifications with lazy transforms and owned cancellation."""
import asyncio
from collections import deque
from types import SimpleNamespace

from dsh.core.session.types import SessionLogOffset
from dsh.typert.remote import RemoteError


class ListenerBuffer:
    def __init__(self, ctx, signal):
        signal.throwIfAborted()
        self.values, self.transforms, self.cleanup = deque(), [], []
        self.wake = asyncio.Event()
        self.closed, self.consumed, self.failure = False, False, None
        def close(*_): self.dispose()
        signal.addEventListener('abort', close, dict(once=True))
        self.own(lambda: signal.removeEventListener('abort', close))
        try:
            dispose = ctx.effect(lambda: close, 'session-controller.listener-buffer')
            self.own(dispose)
        except BaseException:
            self.dispose()
            raise

    def own(self, dispose):
        if self.closed:
            dispose()
        else:
            self.cleanup.append(dispose)

    def capture(self, action):
        if self.closed:
            return
        try:
            action()
        except BaseException as error:
            self.failure = error
            self.dispose()

    def createInput(self, transform):
        if self.closed:
            raise RuntimeError('Cannot register a transform on a closed listener buffer')
        index = len(self.transforms)
        self.transforms.append(transform)
        def enqueue(item, front=False):
            if self.closed:
                return
            if front:
                self.values.appendleft((index, item))
            else:
                self.values.append((index, item))
            self.wake.set()
        return SimpleNamespace(append=enqueue, prepend=lambda item: enqueue(item, True))

    async def items(self):
        if self.consumed:
            raise RemoteError('gateway/internal', 'Session listener already has a consumer', {})
        self.consumed = True
        try:
            while True:
                if self.failure is not None:
                    raise self.failure
                if self.closed:
                    return
                if not self.values:
                    self.wake.clear()
                    await self.wake.wait()
                    continue
                index, value = self.values.popleft()
                for item in self.transforms[index](value):
                    if self.failure is not None:
                        raise self.failure
                    if self.closed:
                        return
                    yield item
        finally:
            self.dispose()

    def dispose(self):
        if self.closed:
            return
        self.closed = True
        self.values.clear()
        self.transforms.clear()
        self.wake.set()
        cleanup, self.cleanup = self.cleanup, []
        for dispose in reversed(cleanup):
            dispose()


def event_item(item, next_seq=None):
    if item['type'] == 'event':
        event = item['event']
        if next_seq is not None and event['seq'] < next_seq:
            return dict(events=[], next=next_seq)
        if next_seq is not None and event['seq'] != next_seq:
            raise RemoteError('gateway/internal', 'session event stream skipped seq {}'.format(next_seq), {})
        return dict(events=[event], next=event['seq'] + 1)
    start = next_seq if next_seq is not None else item['session'].firstLiveSeq
    if start >= item['end']:
        return dict(events=[], next=next_seq)
    events = item['session'].snapshotEvents(SessionLogOffset(start), SessionLogOffset(item['end']))
    for event in events:
        if next_seq is not None and event['seq'] != next_seq:
            raise RemoteError('gateway/internal', 'session event stream skipped seq {}'.format(next_seq), {})
        next_seq = event['seq'] + 1
    return dict(events=events, next=next_seq)


class EventListener:
    def __init__(self, ctx, session_id, signal, queue=None):
        signal.throwIfAborted()
        self.disposes, self.first_received, self.next_expected = [], None, None
        buffer = queue if queue is not None else ListenerBuffer(ctx, signal)
        self.buffer = buffer if queue is None else None
        input = buffer.createInput(self.transform)
        def event(session, event):
            if session.id != session_id:
                return
            def capture():
                self.record_first(event['seq'])
                input.append(dict(type='event', session=session, event=event))
            buffer.capture(capture)
        def created(session):
            if session.id != session_id:
                return
            def capture():
                if session.firstLiveSeq < session.seq:
                    self.record_first(session.firstLiveSeq)
                input.prepend(dict(type='created', session=session, end=session.seq))
            buffer.capture(capture)
        try:
            self.disposes.append(ctx.on('session/event', event, global_listener=True))
            self.disposes.append(ctx.on('session/created', created, global_listener=True))
            if self.buffer is not None:
                self.buffer.own(self.dispose)
        except BaseException:
            self.dispose()
            raise

    def record_first(self, seq):
        self.first_received = seq if self.first_received is None else min(self.first_received, seq)

    def setCursor(self, cursor):
        self.next_expected = cursor + 1

    def transform(self, item):
        if not self.disposes:
            return
        if self.next_expected is None:
            self.next_expected = self.first_received
        result = event_item(item, self.next_expected)
        self.next_expected = result['next']
        for event in result['events']:
            if not self.disposes:
                return
            yield dict(type='event', event=event)

    async def events(self):
        if self.buffer is None:
            raise RuntimeError('Consume the externally owned history buffer directly')
        source = self.buffer.items()
        try:
            async for item in source:
                yield item
        finally:
            await source.aclose()
            self.dispose()

    def dispose(self):
        disposes, self.disposes = self.disposes, []
        for dispose in reversed(disposes):
            dispose()
        if self.buffer is not None:
            self.buffer.dispose()


class ProjectionListener:
    def __init__(self, ctx, session_id, signal):
        self.buffer = ListenerBuffer(ctx, signal)
        input = self.buffer.createInput(lambda item: [item])
        def changed(session, changes, seq):
            if session.id == session_id:
                self.buffer.capture(lambda: input.append(dict(session=session,
                    change=dict(type='projection', seq=seq, changes=changes))))
        try:
            self.buffer.own(ctx.get('sessionProjections').onEventChanged(changed))
        except BaseException:
            self.buffer.dispose()
            raise

    async def changes(self):
        source = self.buffer.items()
        try:
            async for item in source:
                yield item['change']
        finally:
            await source.aclose()
            self.dispose()

    def dispose(self):
        self.buffer.dispose()
