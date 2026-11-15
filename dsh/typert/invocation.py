"""One invocation's signal, single-consumer decoded uplink, and teardown."""
import asyncio
import inspect
from dsh.core.abort import AbortController, NEVER_ABORTED
from dsh.core.cancellation import subscribe_abort
from dsh.core.session.json import UNDEFINED
from dsh.typert.artifact import UNDEFINED as CODEC_UNDEFINED
from dsh.typert.dispatch import decode
from dsh.typert.remote import RemoteError, remote_error_of


def cancelled(endpoint, cause=None):
    return RemoteError('gateway/cancelled', 'Remote invocation "%s" was aborted' % endpoint, {}, cause)


def abort_failure(endpoint, signal):
    return signal.reason if remote_error_of(signal.reason) is not None else cancelled(endpoint, signal.reason)


async def empty_uplink():
    if False:
        yield None


def _consume(task):
    if not task.cancelled():
        task.exception()


class UplinkDecoder:
    def __init__(self, source, codec, endpoint, signal, abort):
        self.source, self.codec, self.endpoint = source.__aiter__(), codec, endpoint
        self.signal, self.abort, self.closed = signal, abort, False
        self.interrupted, self.reads = set(), set()
        def on_abort(*_):
            for future in list(self.interrupted):
                if not future.done():
                    future.set_exception(abort_failure(endpoint, signal))
        self.unsubscribe = subscribe_abort(signal, on_abort)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.signal.aborted:
            raise abort_failure(self.endpoint, self.signal)
        if self.closed:
            raise StopAsyncIteration
        interrupted = asyncio.get_running_loop().create_future()
        interrupted.add_done_callback(_consume)
        self.interrupted.add(interrupted)
        read = asyncio.ensure_future(self.source.__anext__())
        self.reads.add(read)
        read.add_done_callback(self.reads.discard)
        read.add_done_callback(_consume)
        try:
            done, _ = await asyncio.wait([read, interrupted], return_when=asyncio.FIRST_COMPLETED)
            if interrupted in done:
                await interrupted
                raise StopAsyncIteration
            try:
                value = await read
            except StopAsyncIteration:
                self.finish()
                raise
        finally:
            self.interrupted.discard(interrupted)
            if not interrupted.done():
                interrupted.cancel()
        try:
            if value is UNDEFINED and self.codec['mode'] == 'src-json':
                return value
            decoded = decode(self.codec, CODEC_UNDEFINED if value is UNDEFINED else value, self.endpoint, 'uplink')
            return UNDEFINED if decoded is CODEC_UNDEFINED else decoded
        except Exception as error:
            self.abort(error)
            raise

    def finish(self):
        self.closed = True
        self.unsubscribe()
        for future in list(self.interrupted):
            if not future.done():
                future.set_result(None)

    async def aclose(self):
        already_closed = self.closed
        self.finish()
        # A Python async generator cannot close while __anext__ is running.
        # Own and settle those reads before returning its carrier iterator.
        reads = list(self.reads)
        for read in reads:
            if not read.done():
                read.cancel()
        if reads:
            await asyncio.gather(*reads, return_exceptions=True)
        close = getattr(self.source, 'aclose', None)
        if close is not None and not already_closed:
            await close()


class GatewayInvocation:
    def __init__(self, request, service, peer, signal, source, codec, endpoint, abort, window=None, subscriptions=()):
        self.request, self.service, self.peer, self.signal = request, service, peer, signal
        self.source, self.codec, self.endpoint, self.abort = source, codec, endpoint, abort
        self.uplinkWindow, self.subscriptions = window, list(subscriptions)
        self.taken, self.decoder, self.closing = False, None, None

    def uplink(self):
        if self.taken:
            raise RuntimeError('typert gateway: %s: invocation.uplink() is available once per call' % self.endpoint)
        self.taken = True
        self.decoder = UplinkDecoder(self.source, self.codec, self.endpoint, self.signal, self.abort)
        return self.decoder

    async def close(self):
        if self.closing is None:
            self.closing = asyncio.ensure_future(self._close())
        await asyncio.shield(self.closing)

    async def _close(self):
        self.taken = True
        try:
            if self.decoder is not None:
                await self.decoder.aclose()
            else:
                close = getattr(self.source.__aiter__(), 'aclose', None)
                if close is not None:
                    task = asyncio.ensure_future(close())
                    task.add_done_callback(_consume)
        finally:
            self.release_subscriptions()

    def release_subscriptions(self):
        for dispose in self.subscriptions:
            dispose()
        self.subscriptions.clear()


def create_invocation(request, descriptor, control):
    carrier = request.get('signal') or NEVER_ABORTED
    subscriptions = []
    if 'uplink' not in request and descriptor.get('mode') != 'stream':
        signal = carrier
    else:
        combined = AbortController()
        sources = [carrier, control.signal]
        if descriptor.get('mode') == 'stream':
            sources.append(request['peer'].signal)
        for source in sources:
            subscriptions.append(subscribe_abort(source, combined.abort))
        signal = combined.signal
    return GatewayInvocation(dict(namespace=request['namespace'], method=request['method'], args=request['args']),
        descriptor['service'], request['peer'], signal, request.get('uplink') or empty_uplink(),
        descriptor.get('uplink', {}).get('codec', dict(mode='src-json')), request['namespace'] + '/' + request['method'],
        control.abort, request.get('uplinkWindow'), subscriptions)


async def invocation_stream(source, endpoint, invocation):
    iterator = source.__aiter__() if hasattr(source, '__aiter__') else iter(source)
    signal = invocation.signal
    aborted = asyncio.ensure_future(signal.wait_aborted())
    pending = None
    try:
        while True:
            if signal.aborted:
                raise abort_failure(endpoint, signal)
            if hasattr(iterator, '__anext__'):
                pending = asyncio.ensure_future(iterator.__anext__())
                await asyncio.wait([pending, aborted], return_when=asyncio.FIRST_COMPLETED)
                if signal.aborted:
                    raise abort_failure(endpoint, signal)
                try:
                    value = await pending
                except StopAsyncIteration:
                    return
            else:
                try:
                    value = next(iterator)
                except StopIteration:
                    return
            yield value
    finally:
        # Wake a method blocked on the uplink before closing its downlink.
        await invocation.close()
        aborted.cancel()
        if pending is not None and not pending.done():
            pending.cancel()
        await asyncio.gather(*([aborted, pending] if pending is not None else [aborted]), return_exceptions=True)
        close = getattr(iterator, 'aclose', None) or getattr(iterator, 'close', None)
        if close is not None:
            value = close()
            if inspect.isawaitable(value):
                await value


class InvocationStream:
    """Drop native strong joins even when a stream is returned before first read."""
    def __init__(self, source, endpoint, invocation):
        self.iterator = invocation_stream(source, endpoint, invocation)
        self.invocation, self.started, self.closed = invocation, False, False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed:
            raise StopAsyncIteration
        self.started = True
        return await self.iterator.__anext__()

    async def aclose(self):
        self.closed = True
        if not self.started:
            self.invocation.release_subscriptions()
        await self.iterator.aclose()
