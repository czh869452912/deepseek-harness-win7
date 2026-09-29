"""Application-owned allowlist bridging Cordis events to Gateway generations."""
import asyncio
import inspect
import os

from dsh.cordis.plugin import Plugin
from dsh.core.scope import carrier_key_of
from dsh.typert.artifact import UNDEFINED
from dsh.typert.remote_events import lossless

EMIT_EVENTS = (
    'agent-preset/selected', 'api-session/activity', 'api-session/added', 'api-session/error',
    'api-session/removed', 'api-session/status', 'commands/change', 'credentials/reference-updated',
    'cordis/request-run', 'cordis/request-run-resolved', 'cordis/dynamic-package',
    'cordis/dynamic-retract', 'cordis/inspect-query', 'cordis/inspect-query-resolved',
    'llm/adapters-updated', 'settings/document-updated',
)
WATERFALL_EVENTS = ('approval/request', 'user-questions/request')


class ForwardedEventSource:
    def __init__(self, ctx, signal):
        self.queue, self.closed, self.signal = asyncio.Queue(), False, signal
        self.disposers, self.pending = [], set()
        for event in EMIT_EVENTS:
            def emit(*args, _event=event):
                for index, value in enumerate(args):
                    try:
                        lossless(value)
                    except Exception as error:
                        raise ValueError('forwarded host event "%s" argument %s is not lossless JSON data' % (_event, index)) from error
                self.push({'event': _event, 'args': list(args)})
            self.disposers.append(ctx.on(event, emit))
        for event in WATERFALL_EVENTS:
            def waterfall(request, next_fn, *, caller_ctx=None, _event=event):
                subject = carrier_key_of(caller_ctx)
                if subject is None:
                    return next_fn()
                child = getattr(subject, 'ctx', None)
                if child is None:
                    raise TypeError('forwarded scoped event has no live Context')
                future = asyncio.get_running_loop().create_future()
                self.pending.add(future)
                async def delegate():
                    try:
                        result = next_fn()
                        if inspect.isawaitable(result):
                            result = await result
                        if not future.done():
                            future.set_result(result)
                    except BaseException as error:
                        if not future.done():
                            future.set_exception(error)
                def resolve(outcome):
                    if future.done():
                        return
                    if outcome['kind'] == 'result':
                        future.set_result(outcome.get('value', UNDEFINED))
                    else:
                        asyncio.create_task(delegate())
                def reject(error):
                    if not future.done():
                        future.set_exception(error if isinstance(error, BaseException) else RuntimeError(str(error)))
                dispatch = dict(event=_event, request=request, context=dict(value=child, subject=subject), resolve=resolve, reject=reject)
                if not self.push(dispatch):
                    asyncio.create_task(delegate())
                async def wait():
                    try:
                        return await future
                    finally:
                        self.pending.discard(future)
                return wait()
            self.disposers.append(ctx.on(event, waterfall))
        self.release_abort = signal.add_listener('abort', lambda *_: self.end())

    def push(self, frame):
        if self.closed:
            return False
        self.queue.put_nowait(frame)
        return True

    def end(self):
        if self.closed:
            return
        self.closed = True
        # A source may be removed before its async iterator is first advanced.
        # Abort therefore owns listener cleanup, not only the iterator finally.
        for dispose in self.disposers:
            dispose()
        self.disposers.clear()
        reason = self.signal.reason if self.signal.aborted else RuntimeError('api-remotes: forwarded Remote event source ended')
        while not self.queue.empty():
            frame = self.queue.get_nowait()
            if frame and 'context' in frame:
                frame['reject'](reason)
        self.queue.put_nowait(None)

    async def iterate(self):
        try:
            while not self.closed and not self.signal.aborted:
                frame = await self.queue.get()
                if frame is None:
                    return
                yield frame
        finally:
            self.release_abort()
            self.end()
            for dispose in self.disposers:
                dispose()


class ApiRemotesPlugin(Plugin):
    id = 'api-remotes'
    inject = ['typertGateway']

    def apply(self, ctx):
        def source(signal):
            return ForwardedEventSource(ctx, signal).iterate()
        ctx.effect(lambda: ctx.get('typertGateway').registerRemoteEvents(source, {'home': os.path.expanduser('~')}),
                   'api-remotes: forwarded Cordis event source')
