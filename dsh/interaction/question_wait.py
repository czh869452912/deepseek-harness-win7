"""Host deadline that pauses while a connected question UI holds a claim."""
import asyncio
import time

from dsh.core.abort import AbortController


class TimedQuestionWait:
    def __init__(self, deadline, parent, timeout):
        self.deadline, self.parent, self.timeout = deadline, parent, timeout
        self.controller = AbortController()
        self.done = asyncio.get_running_loop().create_future()
        self.claims = set()
        self.timer = None
        self._parent_aborted = lambda *_: self.close(parent.reason)
        if parent is not None:
            parent.addEventListener('abort', self._parent_aborted, dict(once=True))
        if parent is not None and parent.aborted:
            self._parent_aborted()
        else:
            self._schedule()

    @property
    def signal(self):
        return self.controller.signal

    @staticmethod
    def now():
        return time.time() * 1000

    def _schedule(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if not self.signal.aborted and not self.claims:
            self.timer = asyncio.get_running_loop().call_later(max(0, self.deadline - self.now()) / 1000,
                                                              self.close, self.timeout)

    async def attach(self, signal):
        if signal.aborted or self.signal.aborted:
            return
        if not self.claims and self.now() >= self.deadline:
            self.close(self.timeout)
            return
        ended = asyncio.get_running_loop().create_future()
        def release(*_):
            if release not in self.claims:
                return
            self.claims.remove(release)
            signal.removeEventListener('abort', release)
            self.signal.removeEventListener('abort', release)
            if not ended.done():
                ended.set_result(None)
            self._schedule()
        self.claims.add(release)
        signal.addEventListener('abort', release, dict(once=True))
        self.signal.addEventListener('abort', release, dict(once=True))
        self._schedule()
        try:
            yield dict(remainingMs=max(0, self.deadline - self.now()))
            await ended
        finally:
            release()

    def close(self, reason):
        if self.signal.aborted:
            return
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.parent is not None:
            self.parent.removeEventListener('abort', self._parent_aborted)
        self.controller.abort(reason)
        if not self.done.done():
            self.done.set_result(None)
