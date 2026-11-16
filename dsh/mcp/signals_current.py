"""Owned signal fan-in, including the native legacy Event call adapter."""
import asyncio
from contextlib import asynccontextmanager
from dsh.core.abort import AbortController


@asynccontextmanager
async def combined_signals(*signals):
    controller, relays, watchers = AbortController(), [], []
    async def observe(event):
        await event.wait()
        controller.abort()
    try:
        for signal in signals:
            if isinstance(signal,asyncio.Event):
                if signal.is_set():controller.abort()
                else:watchers.append(asyncio.create_task(observe(signal)))
            elif signal is not None:
                relays.append(signal.add_listener('abort',controller.abort))
        yield controller.signal
    finally:
        for detach in relays:detach()
        for task in watchers:task.cancel()
        await asyncio.gather(*watchers,return_exceptions=True)
