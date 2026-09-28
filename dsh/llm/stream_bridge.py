"""Bounded synchronous-reader bridge with explicit consumer cancellation."""
import asyncio
import queue
import threading

class ConsumerSignal:
    def __init__(self, caller=None):
        self.caller, self.stopped = caller, threading.Event()

    @property
    def aborted(self):
        from dsh.core.cancellation import aborted
        return self.stopped.is_set() or aborted(self.caller)


class OwnedStream:
    def __init__(self, factory, caller=None):
        self.signal = ConsumerSignal(caller)
        self.iterator = iter(factory(self.signal))

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def cancel(self):
        self.signal.stopped.set()

    def close(self):
        self.cancel()
        close = getattr(self.iterator, "close", None)
        if close is not None:
            close()


async def iter_chunks(stream, cancel_check=None):
    if hasattr(stream, "__aiter__"):
        iterator = stream.__aiter__()
        pending = None
        try:
            while True:
                if cancel_check and cancel_check():
                    raise asyncio.CancelledError("cancelled")
                pending = asyncio.ensure_future(iterator.__anext__())
                while not pending.done():
                    await asyncio.wait([pending], timeout=0.02)
                    if cancel_check and cancel_check():
                        raise asyncio.CancelledError("cancelled")
                try:
                    item = pending.result()
                except StopAsyncIteration:
                    return
                pending = None
                yield item
        finally:
            if pending is not None:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            close = getattr(iterator, "aclose", None)
            if close:
                await close()
        return
    mailbox, stop, finished = queue.Queue(maxsize=1), threading.Event(), threading.Event()
    demand = threading.Semaphore(0)
    sentinel = object()
    def put(item):
        while not stop.is_set():
            try:
                mailbox.put(item, timeout=0.02)
                return
            except queue.Full:
                pass
    def read():
        try:
            iterator = iter(stream)
            while not stop.is_set():
                if not demand.acquire(timeout=0.02):
                    continue
                if stop.is_set():
                    break
                try:
                    put(next(iterator))
                except StopIteration:
                    break
        except Exception as error:
            put(error)
        finally:
            try:
                close = getattr(stream, "close", None)
                if close:
                    close()
            finally:
                put(sentinel)
                finished.set()
    worker = threading.Thread(target=read, name="dsh-model-reader", daemon=True)
    worker.start()
    try:
        while True:
            demand.release()
            while True:
                if cancel_check and cancel_check():
                    raise asyncio.CancelledError("cancelled")
                try:
                    item = mailbox.get_nowait()
                    break
                except queue.Empty:
                    await asyncio.sleep(0.01)
            if item is sentinel:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stop.set()
        demand.release()
        cancel = getattr(stream, "cancel", None)
        if cancel:
            cancel()
            # Owned transports check cancellation in every I/O phase.
            while not finished.is_set():
                await asyncio.sleep(0.01)
