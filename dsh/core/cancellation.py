"""Read the shared AbortSignal/asyncio.Event cancellation contract."""

import asyncio
import logging

logger = logging.getLogger(__name__)


def aborted(signal):
    return bool(signal is not None and (getattr(signal, "aborted", False) or
                (callable(getattr(signal, "is_set", None)) and signal.is_set())))


def subscribe_abort(signal, callback):
    """Subscribe to native signals and the historical asyncio.Event adapter."""
    if signal is None:
        return lambda: None
    if callable(getattr(signal, "add_listener", None)):
        return signal.add_listener("abort", callback)
    if aborted(signal):
        try:
            callback(getattr(signal, "reason", None))
        except Exception:
            logger.warning("abort listener threw", exc_info=True)
        return lambda: None
    wait = getattr(signal, "wait_aborted", None) or getattr(signal, "wait", None)
    if not callable(wait):
        raise TypeError("cancellation signal must support abort subscriptions or waiting")
    async def watch():
        await wait()
        try:
            callback(getattr(signal, "reason", None))
        except Exception:
            logger.warning("abort listener threw", exc_info=True)
    task = asyncio.create_task(watch())
    return task.cancel
