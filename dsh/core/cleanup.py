"""Stable owner-held operations with independent Python awaiters."""
import asyncio


class SharedPromise:
    def __init__(self,operation):
        self.task=asyncio.ensure_future(operation)
        self.task.add_done_callback(lambda done:None if done.cancelled() else done.exception())
    def __await__(self):return asyncio.shield(self.task).__await__()
    def add_done_callback(self,callback):self.task.add_done_callback(lambda _:callback(self))
    def cancelled(self):return self.task.cancelled()
    def done(self):return self.task.done()
    def result(self):return self.task.result()
    def exception(self):return self.task.exception()


class CleanupPromise(SharedPromise):
    """A cleanup transaction whose waiters cannot cancel its owner."""
