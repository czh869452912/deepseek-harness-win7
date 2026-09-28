"""Bounded synchronous-reader bridge with explicit consumer cancellation."""
import asyncio
import queue
import threading

from dsh.core.cancellation import aborted


class ConsumerSignal:
    def __init__(self, caller=None):
        self.caller, self.stopped = caller, threading.Event()

    @property
    def aborted(self):
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
        try:
            async for item in stream:
                if cancel_check and cancel_check():
                    raise asyncio.CancelledError("cancelled")
                yield item
        finally:
            close = getattr(stream, "aclose", None)
            if close:
                await close()
        return
    mailbox, stop, finished = queue.Queue(maxsize=2), threading.Event(), threading.Event()
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
            for item in stream:
                if stop.is_set():
                    break
                put(item)
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
            if cancel_check and cancel_check():
                raise asyncio.CancelledError("cancelled")
            try:
                item = mailbox.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            if item is sentinel:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        stop.set()
        cancel = getattr(stream, "cancel", None)
        if cancel:
            cancel()
            # Owned transports check cancellation in every I/O phase.
            while not finished.is_set():
                await asyncio.sleep(0.01)
