"""Non-consuming job roster/output generations with bounded coalesced frames."""
import asyncio
import math

from dsh.core.cancellation import subscribe_abort
from dsh.cordis.json_text import stringify_json
from dsh.cordis.utils import js_to_string
from dsh.terminal.grapheme import utf8


class OutputWaiter:
    def __init__(self):
        self.dirty, self.resolve = False, None

    def wake(self):
        self.dirty = True
        if self.resolve is not None:
            self.resolve()

    async def wait(self, signal):
        if self.dirty or signal.aborted:
            self.dirty = False
            return
        future = asyncio.get_running_loop().create_future()
        detach = lambda: None
        def finish(*_):
            detach()
            if self.resolve is finish:
                self.resolve = None
            self.dirty = False
            if not future.done():
                future.set_result(None)
        self.resolve = finish
        detach = subscribe_abort(signal, finish)
        try:
            await future
        finally:
            detach()
            if self.resolve is finish:
                self.resolve = None


async def sleep(ms, signal):
    if signal.aborted:
        return
    future = asyncio.get_running_loop().create_future()
    detach = lambda: None
    def finish(*_):
        timer.cancel()
        detach()
        if not future.done():
            future.set_result(None)
    timer = asyncio.get_running_loop().call_later(ms / 1000.0, finish)
    detach = subscribe_abort(signal, finish)
    try:
        await future
    finally:
        timer.cancel()
        detach()


async def stream_job_rows(registry, request, options, signal):
    signal.throwIfAborted()
    waiter = OutputWaiter()
    def changed(event):
        if event['type'] == 'output':
            return
        owner = event['job'].get('owner')
        if owner is None or owner == request['sessionId']:
            waiter.wake()
    unsubscribe = registry.events.subscribe(dict(owners='all'), changed)
    try:
        yield dict(type='rows', jobs=registry.list(request['sessionId']))
        while True:
            await waiter.wait(signal)
            await sleep(options['flushMs'], signal)
            if signal.aborted:
                return
            yield dict(type='rows', jobs=registry.list(request['sessionId']))
    finally:
        unsubscribe()


def output_frames(chunks, next_offset, lossy, max_frame_bytes):
    batch, size, flagged = [], 0, lossy
    for chunk in chunks:
        batch.append(chunk)
        size += len(utf8(chunk['text']))
        if size >= max_frame_bytes:
            frame = dict(type='output', chunks=batch, next=chunk['at'] + len(utf8(chunk['text'])))
            if flagged:
                frame['lossy'] = True
            yield frame
            flagged, batch, size = False, [], 0
    if batch or flagged:
        frame = dict(type='output', chunks=batch, next=next_offset)
        if flagged:
            frame['lossy'] = True
        yield frame


async def observe_job_output(registry, request, options, signal):
    offset = request.get('from')
    if 'from' in request and (type(offset) not in (int, float) or not math.isfinite(offset)
                             or not 0 <= offset <= 9007199254740991 or int(offset) != offset):
        raise RuntimeError('invalid observe offset: expected a non-negative safe integer, got ' + stringify_json(offset))
    signal.throwIfAborted()
    identity = js_to_string(request['jobId'])
    waiter, removed = OutputWaiter(), []
    def changed(event):
        changed_id = event['id'] if event['type'] == 'output' else event['job']['id']
        if changed_id != identity:
            return
        if event['type'] == 'removed':
            removed[:] = [event['job']]
        waiter.wake()
    unsubscribe = registry.events.subscribe(dict(owners='all'), changed)
    try:
        job = registry.get(identity, request.get('sessionId'))
        cursor = job['output']['earliest'] if offset is None else offset
        yield dict(type='opened', job=job, **{'from': cursor})
        while not signal.aborted:
            if removed:
                yield dict(type='status', job=removed[0])
                return
            read = registry.readAt(identity, cursor, request.get('sessionId'))
            if read['chunks'] or read.get('lossy'):
                for frame in output_frames(read['chunks'], read['next'], read.get('lossy', False), options['maxFrameBytes']):
                    yield frame
            cursor = read['next']
            job = registry.get(identity, request.get('sessionId'))
            if job['status'] not in ('running', 'stopping') and cursor >= job['output']['total']:
                yield dict(type='status', job=job)
                return
            await waiter.wait(signal)
            await sleep(options['flushMs'], signal)
    finally:
        unsubscribe()
