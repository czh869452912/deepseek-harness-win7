"""Byte-bounded terminal Remote follower independent of process ownership."""
import asyncio
from collections import deque

from dsh.cordis.json_text import stringify_json


class TerminalFollower:
    def __init__(self, max_bytes):
        self.maximum = max_bytes;self.queue = deque();self.bytes = 0
        self.wake = None;self.closed = False;self.finished = False;self.failure = None

    @property
    def active(self):return not self.closed and not self.finished

    def notify(self):
        if self.wake is not None and not self.wake.done():self.wake.set_result(None)

    def push(self, frame):
        if not self.active:return
        size = len(stringify_json(frame).encode('utf-8'))
        if self.bytes + size > self.maximum:
            self.fail(RuntimeError('Terminal output consumer exceeded its buffer; reconnect to recover the current screen'));return
        self.queue.append((frame, size));self.bytes += size;self.notify()

    def fail(self, error):
        if not self.active:return
        self.failure = error;self.close()

    def finish(self):self.finished = True;self.notify()

    def close(self):
        self.closed = True;self.queue.clear();self.bytes = 0;self.notify()

    async def read(self, signal):
        def abort(*_):self.close()
        signal.addEventListener('abort', abort, dict(once=True))
        if signal.aborted:abort()
        try:
            while not self.closed:
                if self.queue:
                    frame, size = self.queue.popleft();self.bytes -= size;yield frame
                else:
                    if self.finished:break
                    self.wake = asyncio.get_running_loop().create_future()
                    await self.wake;self.wake = None
            if self.failure is not None:raise self.failure
        finally:
            signal.removeEventListener('abort', abort);self.close()
