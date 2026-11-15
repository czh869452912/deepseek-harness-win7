"""One bounded consumer queue; account for complete UTF-8 carrier frames."""
import asyncio
from collections import deque
from dsh.typert.remote import RemoteError


class UplinkInbox:
    def __init__(self, max_bytes, endpoint, on_violation):
        self.max_bytes, self.endpoint, self.on_violation = max_bytes, endpoint, on_violation
        self.queue, self.bytes = deque(), 0
        self.ended = self.closed = self.taken = False
        self.failure = self.wake = None

    def push(self, value, frame_bytes):
        if self.failure is not None or self.closed:
            return
        if self.ended:
            self._violate(RemoteError('gateway/protocol', 'api gateway: Remote stream uplink item after end', dict(endpoint=self.endpoint)))
            return
        if self.bytes + frame_bytes > self.max_bytes:
            self._violate(RemoteError('gateway/uplink-overflow', 'api gateway: Remote stream uplink exceeded {} buffered bytes'.format(self.max_bytes), dict(endpoint=self.endpoint)))
            return
        self.queue.append((value, frame_bytes))
        self.bytes += frame_bytes
        self._signal()

    def end(self):
        if not self.ended:
            self.ended = True
            self._signal()

    def fail(self, error):
        if self.failure is None:
            self.failure = error
            self.queue.clear()
            self.bytes = 0
            self._signal()

    def __aiter__(self):
        if self.taken:
            raise RuntimeError('api gateway: Remote stream uplink inbox already has a consumer')
        self.taken = True
        return self

    async def __anext__(self):
        while True:
            if self.closed:
                raise StopAsyncIteration
            if self.queue:
                value, count = self.queue.popleft()
                self.bytes -= count
                return value
            if self.failure is not None:
                raise self.failure
            if self.ended:
                raise StopAsyncIteration
            if self.wake is not None:
                raise RuntimeError('api gateway: Remote stream uplink inbox has one pending read')
            pending = self.wake = asyncio.get_running_loop().create_future()
            try:
                await asyncio.shield(pending)
            finally:
                # A Python task can be cancelled independently of the JS-style
                # source; release its pending-reader slot without closing the queue.
                if self.wake is pending:
                    self.wake = None

    async def aclose(self):
        self.closed = True
        self.queue.clear()
        self.bytes = 0
        self._signal()

    def _violate(self, error):
        self.fail(error)
        self.on_violation(error)

    def _signal(self):
        pending, self.wake = self.wake, None
        if pending is not None and not pending.done():
            pending.set_result(None)
